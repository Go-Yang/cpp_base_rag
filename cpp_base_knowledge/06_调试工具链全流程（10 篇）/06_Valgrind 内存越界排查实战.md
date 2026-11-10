# Valgrind 内存越界排查实战

## 一、前言

Memcheck 除了泄漏，还擅长抓越界读写和未初始化使用。它的优势是**不需要重新编译**，适合线上二进制的离线复现。

核心总纲：**Memcheck 看"这次访问是否落在合法分配块内"；越界地址会告诉你它在哪个块的边界外多少字节。** 关键是读分配栈和访问栈。

## 二、常见错误类型

### 1. Invalid read / write

```text
Invalid read of size 4
   at 0x4005B6: process (buf.c:88)
 Address 0x5204064 is 0 bytes after a block of size 64 alloc'd
   at 0x4C29F73: malloc (vg_replace_malloc.c:309)
   by 0x4005A1: load (buf.c:40)
```

- `Invalid read/write of size N`：访问了非法地址；
- `0 bytes after a block`：刚好在分配块末尾之后（off-by-one）；
- `N bytes before a block`：块前越界；
- `inside a block of size N free'd`：use-after-free。

### 2. Use of uninitialised value

```text
Conditional jump or move depends on uninitialised value(s)
```

分支/循环条件依赖未初始化内存，程序行为不确定。

加 `--track-origins=yes` 可以看到未初始化值的来源：

```text
Uninitialised value was created by a heap allocation
```

### 3. Invalid free / double free

```text
Invalid free() / delete / delete[] / realloc()
Address 0x... is 0 bytes inside a block of size 32 free'd
```

说明释放了未分配/已释放/非堆地址。

### 4. Mismatched free / delete

```text
Mismatched free() / delete / delete[]
```

`new[]` 配了 `free`，或 `malloc` 配了 `delete`。

## 三、基本命令

```bash
valgrind --tool=memcheck \
         --track-origins=yes \
         --leak-check=full \
         --num-callers=30 \
         --error-exitcode=1 \
         --log-file=vg.log \
         ./app
```

- `--track-origins=yes`：追踪未初始化值来源（开销更大）；
- `--read-var-info=yes`：配合 `-g` 显示变量名；
- `--undef-value-errors=yes`：默认开启未初始化检查；
- `--partial-loads-ok=no`：更严格地检查部分加载。

## 四、读报告的方法

一条 Invalid read/write 包含三部分信息：

1. **访问**：哪行代码、读/写、多少字节；
2. **地址**：越界地址；
3. **分配块**：这块内存是谁分配的、多大、越界多少字节。

排序建议：

- 先修写越界（破坏数据）；
- 再修读越界（可能读到垃圾）；
- 再修未初始化；
- 最后处理泄漏。

## 五、典型实战

### 1. off-by-one

```c
char* buf = malloc(8);
for (int i = 0; i <= 8; i++) buf[i] = 0;
```

报告：

```text
Invalid write of size 1
Address ... is 0 bytes after a block of size 8 alloc'd
```

修复：`i < 8`。

### 2. 结构体越界

```c
struct S { int a; char b; };
struct S* s = malloc(sizeof(struct S));
((char*)s)[sizeof(struct S)] = 0;   // 末尾之后
```

按字节操作结构体时要严格用 `sizeof`，并注意填充。

### 3. use-after-free

```c
char* p = malloc(16);
free(p);
printf("%s", p);
```

报告会在失败路径上指出该块已 free。修复：置空/明确所有权。

### 4. uninitialised value

```c
int x;
if (x > 0) { ... }   // 未初始化
```

加 `--track-origins=yes` 定位分配点，初始化或重构。

### 5. 读越界不崩

```c
int arr[4];
int sum = 0;
for (int i = 0; i < 5; i++) sum += arr[i];   // 读越界
```

可能读到栈上垃圾值，程序不崩但结果错误。Valgrind 能报 invalid read。

## 六、抑制与误报

系统库、第三方库的已知问题会干扰报告。用：

```bash
valgrind --gen-suppressions=all ./app > supp.txt
```

把 `{ ... }` 块保存到 `app.supp`：

```bash
valgrind --suppressions=app.supp ./app
```

注意：

- 抑制要精确到调用栈，不要用通配符掩盖自己的代码；
- 定期审查抑制项；
- 自研分配器可能让 Valgrind 误报，需要提供客户端的 `VALGRIND_MALLOCLIKE_BLOCK` 标注或直接换 ASAN。

## 七、与 ASAN 的取舍

| 场景 | 推荐 |
|---|---|
| 日常开发/CI | ASAN（快、栈清晰） |
| 没有重新编译条件 | Valgrind |
| 未初始化值 | Valgrind `--track-origins` 或 MSAN |
| 自定义分配器 | ASAN 通常更友好 |
| 并发问题 | TSan / Helgrind |

两者交叉验证能提高置信度。

## 八、排查流程

1. 准备可复现的输入；
2. 跑 Memcheck，保存日志；
3. 先看 Invalid write，再看 read、uninitialised；
4. 读访问栈 + 分配栈，确认边界；
5. 修复后重跑，确认错误消失；
6. 加 ASAN/单元测试防回归。

## 九、面试标准简答

### 1. Valgrind 怎么发现越界？

它维护每个分配块的边界元数据，插桩检查每次内存访问是否落在合法块内，并报告访问地址相对块边界的偏移。

### 2. "0 bytes after a block" 是什么意思？

访问地址刚好在分配块末尾之后，典型的 off-by-one。常见于循环 `<=`、字符串少了 `\0`、长度算多 1。

### 3. Valgrind 能检测未初始化值吗？

能，Memcheck 会跟踪未初始化内存，分支依赖未初始化值时报错；加 `--track-origins=yes` 可追踪来源。

### 4. 为什么 Valgrind 会误报？

自研分配器/内存池、内联汇编、部分系统调用、静态链接 libc 等场景可能让 Valgrind 无法正确理解内存生命周期。可用客户端标注或抑制文件处理。

## 十、极简口诀

**Invalid read/write 看边界，分配栈定来源；**

**0 bytes after 是 off-by-one，free'd 是 UAF；**

**未初始化加 track-origins；**

**第三方误报用 suppression，自研池换 ASAN。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
