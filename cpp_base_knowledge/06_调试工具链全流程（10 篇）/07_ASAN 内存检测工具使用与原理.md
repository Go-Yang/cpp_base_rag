# ASAN 内存检测工具使用与原理

## 一、前言

AddressSanitizer（ASAN）是编译器内置的内存错误检测工具，能发现：

- 堆/栈/全局缓冲区越界；
- use-after-free；
- double free / invalid free；
- 内存泄漏（LeakSanitizer 集成）；
- 部分未定义行为（配合 UBSan）。

核心总纲：**ASAN 用影子内存记录每个字节的可访问性，在分配周围加红区，访问时检查影子内存。** 它比 Valgrind 快得多（约 2 倍开销），适合日常开发和 CI。

## 二、基本使用

### 1. 编译与链接

```bash
gcc -fsanitize=address \
    -fno-omit-frame-pointer \
    -g \
    app.c -o app
```

- `-fsanitize=address` 编译和链接都要加；
- `-fno-omit-frame-pointer` 保证调用栈完整；
- `-g` 保留源码行号。

C++ 同理用 `g++`；CMake 中：

```cmake
target_compile_options(app PRIVATE -fsanitize=address -fno-omit-frame-pointer -g)
target_link_options(app PRIVATE -fsanitize=address)
```

### 2. 运行

```bash
./app
# 或带选项
ASAN_OPTIONS=halt_on_error=1:abort_on_error=1:detect_leaks=1 ./app
```

### 3. 常用 ASAN_OPTIONS

| 选项 | 作用 |
|---|---|
| `halt_on_error=1` | 第一次错误就停 |
| `abort_on_error=1` | 用 abort 终止，便于拿 core |
| `detect_leaks=1` | 开启泄漏检测（默认开） |
| `detect_stack_use_after_return=1` | 检测返回后使用栈变量 |
| `quarantine_size_mb=256` | 隔离区大小 |
| `log_path=asan.log` | 输出到文件 |
| `symbolize=1` | 符号化 |
| `suppressions=asan.supp` | 抑制文件 |

## 三、原理

### 1. 影子内存

ASAN 把虚拟地址空间的一部分作为影子内存，每 8 字节应用内存对应 1 字节影子：

- 0 表示全部可访问；
- 1–7 表示前 N 字节可访问；
- 负数表示红区/已释放。

每次内存访问前插入检查：读取影子值，判断访问范围是否合法。

### 2. 红区

分配块周围放置红区（redzone）：

```text
[红区][用户数据][红区]
```

越界读写红区会立即触发错误。

### 3. 隔离区（quarantine）

`free` 后内存不立即复用，先放入隔离区。这样 use-after-free 更容易被捕获；隔离区大小可配置。

### 4. 分配器替换

ASAN 接管 `malloc/free`、`new/delete`，记录分配/释放栈，检测 double free、invalid free。

### 5. 栈与全局

- 栈变量周围插入红区，检测栈越界；
- 全局变量周围插入红区，检测全局越界；
- 栈返回后使用需要 `detect_stack_use_after_return=1`。

## 四、常见错误报告

### 1. heap-buffer-overflow

```text
ERROR: AddressSanitizer: heap-buffer-overflow on address ...
WRITE of size 4 at ...
#0 ... process app.c:42
0x... is located 0 bytes after 64-byte region
allocated by thread T0 here:
    #0 malloc
    #1 load app.c:30
```

直接给出访问点、分配点、越界偏移。

### 2. use-after-free

```text
ERROR: AddressSanitizer: heap-use-after-free
READ of size 4 ...
freed by thread T0 here:
    #0 free
    #1 release app.c:88
previously allocated by thread T0 here:
    #0 malloc
    #1 create app.c:60
```

### 3. stack-buffer-overflow

```text
ERROR: AddressSanitizer: stack-buffer-overflow
```

### 4. double-free

```text
ERROR: AddressSanitizer: attempting double-free
```

### 5. LeakSanitizer

程序退出时：

```text
ERROR: LeakSanitizer: detected memory leaks
Direct leak of 40 byte(s) in 1 object(s) allocated from:
    #0 malloc
    #1 load_config config.c:42
```

## 五、与其他 Sanitizer 的关系

| 工具 | 检测 |
|---|---|
| ASAN | 内存越界、UAF、double free、泄漏 |
| MSAN | 未初始化内存 |
| TSan | 数据竞争 |
| UBSan | 未定义行为（溢出、移位、空指针等） |

它们通常不能同时开启（ASAN 与 TSan 互斥），按需选择。

UBSan 可以单独或与 ASAN 组合：

```bash
gcc -fsanitize=address,undefined -g app.c -o app
```

## 六、常见问题

### 1. ASan runtime does not come first

程序或某个库在 ASAN 之前加载了其他分配器/预加载库。确保主程序用 `-fsanitize=address` 链接；用 `LD_PRELOAD` 时把 ASAN 放最前，或避免混用。

### 2. 静态库没有插桩

ASAN 只能检测插桩过的代码。第三方静态库需要重新编译，或只在其边界检测；未插桩库内部的越界可能漏报。

### 3. 泄漏报告来自第三方库

用抑制文件：

```bash
ASAN_OPTIONS=suppressions=asan.supp ./app
```

格式：

```text
leak:libfoo.so
```

### 4. 与 Valgrind 冲突

ASAN 和 Valgrind 不能同时使用，选一个。

### 5. 生产环境能否开启

ASAN 有性能/内存开销，且会改变内存布局，一般用于测试/灰度，不建议直接上生产；线上可用抽样、专用检测实例或 ASAN 的轻量模式评估。

## 七、实战流程

1. 用 ASAN 重编译复现；
2. 读报告：错误类型、访问点、分配/释放点；
3. 修复边界/生命周期问题；
4. 重跑确认；
5. 把 ASAN 加入 CI（单元测试 + 集成测试）；
6. 对性能敏感路径单独评估开销。

## 八、面试标准简答

### 1. ASAN 的原理是什么？

编译期在每次内存访问前插入检查，运行时通过影子内存判断地址是否可访问；分配器在对象周围加红区，free 后放入隔离区，从而检测越界、UAF、double free。

### 2. ASAN 和 Valgrind 的区别？

ASAN 是编译期插桩 + 影子内存，速度快（约 2 倍开销），需要重新编译；Valgrind 是动态二进制插桩，慢（20–50 倍），但不需要重编译，未初始化检测更强。

### 3. 为什么 ASAN 能检测 use-after-free？

free 后内存进入隔离区，不会立即复用；影子内存标记为不可访问，之后访问会触发错误，并打印分配/释放栈。

### 4. ASAN 有什么局限？

只能检测插桩代码；不检测未初始化（用 MSAN）；有性能和内存开销；与 Valgrind 不兼容；生产环境需谨慎。

## 九、极简口诀

**ASAN 影子内存，红区隔离区；**

**越界 UAF 双释放，报告给三栈；**

**-fsanitize=address，加 -g 加帧指针；**

**日常 CI 跑，生产要评估。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
