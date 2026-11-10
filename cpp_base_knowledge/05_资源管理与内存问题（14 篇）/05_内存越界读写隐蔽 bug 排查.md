# 内存越界读写隐蔽 bug 排查

## 一、前言

越界读写（out-of-bounds read/write）是指访问了分配对象之外的内存。它比空指针更隐蔽：

- 越界几个字节时，往往仍在同一个页内，**不会立刻崩溃**；
- 破坏的可能是相邻变量、堆元数据或别人的对象；
- 崩溃点常常远离真正的越界点。

核心总纲：**越界不一定崩，崩溃不一定在越界处。** 定位要靠工具把"访问"和"分配边界"关联起来。

## 二、常见越界形态

### 1. off-by-one

```c
char buf[8];
for (int i = 0; i <= 8; i++) {   // i == 8 越界
    buf[i] = 0;
}
```

### 2. 长度计算错误

```c
memcpy(dst, src, sizeof(src));   // src 是指针时 sizeof 是指针大小
```

`sizeof` 对指针失效，是经典错误。

### 3. 负下标 / 无符号回绕

```c
int i = -1;
a[i] = 0;          // 越界

size_t n = 0;
n--;               // 回绕成极大值
buf[n] = 0;        // 灾难
```

### 4. 多维数组按一维访问

```c
int a[3][4];
a[0][5] = 1;       // 实际落在 a[1][1]
```

### 5. 字符串缺少终止符

```c
char buf[4];
memcpy(buf, "abcd", 4);   // 没有 '\0'
printf("%s", buf);        // 读到缓冲区之外
```

### 6. 容器与迭代器越界

```cpp
std::vector<int> v(10);
v[10] = 1;          // operator[] 不检查
v.at(10) = 1;       // 抛 std::out_of_range
```

`erase`/`insert` 后继续使用旧迭代器也属于访问失效内存。

### 7. 结构体布局假设错误

用 `memcpy` 按手算偏移读写结构体，遇到填充、对齐、ABI 差异就出错。

### 8. memcpy 重叠

`memcpy(dst, src, n)` 的源和目标重叠是未定义行为，应使用 `memmove`。

### 9. 读未初始化内存

不是"越界"，但属于同一类内存错误：读到栈/堆上的垃圾值，行为不确定。

## 三、为什么难以发现

### 1. 页粒度保护

内存保护以页（4KB）为单位。越界几个字节仍在同一页内，MMU 不会报错。只有越过页边界才触发 `SIGSEGV`。

### 2. 分配器复用

释放的内存被复用后，越界写入会破坏新对象，问题出现在别处。

### 3. 优化与布局变化

`-O2`、不同编译器、不同结构体布局会让 bug 时隐时现。

### 4. 读写不对称

越界读可能只读到垃圾值，不崩溃；越界写才破坏数据。

## 四、检测工具

### 1. ASAN（首选）

```bash
gcc -fsanitize=address -fno-omit-frame-pointer -g app.c -o app
```

ASAN 在每次分配周围加红区，越界访问红区会立即报错，并给出分配、访问两处调用栈。支持：

- heap-buffer-overflow；
- stack-buffer-overflow；
- global-buffer-overflow；
- use-after-free；
- container-overflow（配合注解）。

### 2. Valgrind Memcheck

```bash
valgrind --tool=memcheck --track-origins=yes ./app
```

能报 invalid read/write of size N，适合不方便重编译的场景。

### 3. 编译器/标准库检查

- `-fsanitize=undefined`：有符号溢出、移位、空指针等；
- `_GLIBCXX_DEBUG`：STL 迭代器、`operator[]` 越界检查；
- `-D_GLIBCXX_ASSERTIONS`：轻量断言；
- `-fsanitize=bounds`：数组边界。

### 4. 页保护分配器

- Electric Fence（`efence`）：每次分配单独占页，越界立刻崩；
- glibc `MALLOC_PERTURB_`：填充垃圾值，提高暴露概率；
- `mprotect` 手动设置保护页做单元测试。

### 5. 静态分析

- Clang Static Analyzer；
- Coverity、PVS-Studio；
- `-Wall -Wextra -Warray-bounds`。

## 五、排查流程

1. **用 ASAN 复现**：拿到越界访问的地址和调用栈；
2. **确认分配边界**：是哪个 `malloc`/数组/容器分配的，大小多少；
3. **检查索引和长度计算**：off-by-one、`sizeof`、有符号/无符号；
4. **检查容器失效**：扩容、erase、迭代器；
5. **修复并回归**：ASAN + 单元测试 + fuzz。

```bash
ASAN_OPTIONS=halt_on_error=1:abort_on_error=1 ./app
```

## 六、修复与预防

1. 用 `std::array`、`std::vector`、`std::string`，减少裸数组。
2. 访问用 `.at()` 或显式边界检查；对外部输入先校验长度。
3. 长度统一用 `size_t`，避免负数转无符号。
4. `memcpy` 的长度用 `sizeof` 时确认操作数是数组而不是指针。
5. 字符串操作保证 `\0`，优先 `std::string`。
6. 容器扩容后重新获取指针/迭代器。
7. 结构体序列化用字段逐个处理，不按内存布局整体拷贝。
8. CI 中开启 ASAN/UBSAN，关键模块加 fuzz。

## 七、面试标准简答

### 1. 为什么越界读写经常不崩溃？

内存保护以页为单位，越界几个字节通常仍在同一页内，硬件不会报错。只有跨页或破坏分配器元数据时才暴露。

### 2. ASAN 如何检测越界？

ASAN 在分配对象周围放置红区（redzone），并用影子内存记录每个字节的可访问性。访问红区时检查影子内存，立即报错并打印分配/访问调用栈。

### 3. sizeof 指针为什么会导致越界？

指针的大小是地址宽度（4/8 字节），不是它指向的数组长度。`memcpy(dst, src, sizeof(src))` 在 `src` 是指针时只复制 8 字节，若原意是复制整个数组，就会读不完整；反过来按错误的大小写入也可能越界。

### 4. 如何预防容器迭代器失效？

不要在遍历中修改容器结构；需要时用索引、重新获取迭代器，或先收集操作再统一执行。不同容器失效规则不同，要查标准。

## 八、极简口诀

**越界几字节不崩，跨页毁元数据才响；**

**off-by-one、sizeof 针、无符号回绕是常客；**

**ASAN 红区抓现场，valgrind 看大小；**

**容器用 at，长度先校验。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
