# Valgrind 内存泄漏精准检测教程

## 一、前言

Valgrind 的 Memcheck 是最经典的 C/C++ 内存错误检测工具。它通过动态二进制插桩运行程序，能发现：

- 内存泄漏；
- 越界读写；
- 使用未初始化内存；
- use-after-free；
- double free / invalid free。

核心总纲：**Valgrind 慢但全面，适合测试环境精确定位；ASAN 快，适合 CI 和日常开发。** 泄漏定位看 `--leak-check=full` 的分配栈。

## 二、基本命令

```bash
valgrind --tool=memcheck \
         --leak-check=full \
         --show-leak-kinds=all \
         --track-origins=yes \
         --error-exitcode=1 \
         --num-callers=30 \
         --log-file=valgrind.log \
         ./app
```

常用参数：

| 参数 | 作用 |
|---|---|
| `--leak-check=full` | 详细泄漏报告 |
| `--show-leak-kinds=all` | 显示所有泄漏类型 |
| `--track-origins=yes` | 追踪未初始化值的来源 |
| `--error-exitcode=1` | 有错误时返回非 0，适合 CI |
| `--num-callers=30` | 调用栈深度 |
| `--log-file=` | 输出到文件 |
| `--trace-children=yes` | 跟踪子进程 |
| `--leak-resolution=high` | 合并相同泄漏栈 |

编译时加 `-g`，否则栈里只有地址没有行号。

## 三、泄漏分类

| 类型 | 含义 | 处理 |
|---|---|---|
| definitely lost | 确定泄漏，无指针可达 | 必须修 |
| indirectly lost | 父块泄漏导致子块丢失 | 修父块 |
| possibly lost | 指针指向块内部 | 检查是否真实泄漏 |
| still reachable | 退出时仍有指针可达 | 看场景，长周期服务要关注 |
| suppressed | 被抑制规则忽略 | 确认是否已知问题 |

### 输出示例

```text
==12345== 40 bytes in 1 blocks are definitely lost in loss record 1 of 3
==12345==    at 0x4C29F73: malloc (vg_replace_malloc.c:309)
==12345==    by 0x4005B6: load_config (config.c:42)
==12345==    by 0x4006A1: main (main.c:18)
```

直接给出分配点调用栈，定位到 `config.c:42`。

## 四、使用流程

### 1. 准备

- 编译带 `-g`，尽量 `-Og` 或 `-O0`；
- 关闭自定义分配器/内存池（否则 Valgrind 可能误报或漏报）；
- 准备可复现的测试场景。

### 2. 运行

```bash
valgrind --leak-check=full --show-leak-kinds=all --track-origins=yes ./app
```

### 3. 分析

- 先看 `definitely lost`，优先修；
- 再看 `indirectly lost`，通常随父块一起修；
- `still reachable` 若是全局缓存，评估是否有上限；
- 关注"随时间增长"的泄漏，而不是只看退出时快照。

### 4. 抑制

第三方库的已知问题可以生成抑制文件：

```bash
valgrind --gen-suppressions=all ./app
```

把输出中的 `{ ... }` 块放入 `suppressions.supp`，运行时加：

```bash
valgrind --suppressions=suppressions.supp ./app
```

## 五、常见限制

### 1. 性能开销

Valgrind 会让程序慢 20–50 倍，内存占用增加。不适合生产环境或性能测试。

### 2. 改变时序

插桩会改变线程调度和内存布局，某些并发 bug 可能不复现，某些时序 bug 又会新出现。

### 3. 自定义分配器

程序自己管理内存池时，Valgrind 只看到池的 `malloc`，池内部的泄漏无法区分。可以对池实现加标注，或改用 ASAN。

### 4. 静态链接

静态链接的 libc 可能导致误报/漏报，通常需要动态链接运行。

### 5. 只跑特定路径

泄漏检测依赖实际执行到的分配路径。测试覆盖不到的代码，Valgrind 也看不到。

## 六、与 ASAN 的对比

| 维度 | Valgrind | ASAN |
|---|---|---|
| 原理 | 动态二进制插桩 | 编译期插桩 + 影子内存 |
| 速度 | 慢 20–50 倍 | 慢约 2 倍 |
| 覆盖 | 内存错误 + 泄漏 | 内存错误 + 泄漏（LSan） |
| 需要重编译 | 否 | 是 |
| 未初始化检测 | 强 | 需 MSAN（另一套） |
| 适合 | 测试环境精确定位 | 日常开发/CI |

实践中：日常用 ASAN，复杂问题用 Valgrind 交叉验证。

## 七、排查流程

1. 用代表性场景跑 Valgrind；
2. 先修 `definitely lost`；
3. 看分配栈，确认所有权；
4. 修复后重跑，确认泄漏消失；
5. 把 ASAN/LSan 加入 CI，防止回归；
6. 对长周期服务，结合 RSS 曲线和压测观察。

## 八、面试标准简答

### 1. Valgrind 如何检测内存泄漏？

它插桩运行程序，跟踪每次 malloc/free，程序退出时扫描仍分配的块，按可达性分类并打印分配调用栈。

### 2. definitely lost 和 still reachable 的区别？

`definitely lost` 是没有任何指针可达的块，确定泄漏；`still reachable` 是退出时仍有全局/栈指针指向的块，可能是有意缓存，但长周期服务中也可能持续增长。

### 3. Valgrind 有什么缺点？

速度慢、内存开销大、改变时序、对自定义分配器不友好、需要实际执行到泄漏路径；不适合生产环境。

### 4. 如何抑制第三方库的误报？

用 `--gen-suppressions=all` 生成抑制块，保存到抑制文件，运行时 `--suppressions=` 加载。要定期审查抑制项，避免掩盖真实问题。

## 九、极简口诀

**Valgrind 插桩跑，慢但看得全；**

**leak-check full 看分配栈，definitely 先修；**

**still reachable 看场景，第三方差抑制；**

**ASAN 日常跑，Valgrind 做复核。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
