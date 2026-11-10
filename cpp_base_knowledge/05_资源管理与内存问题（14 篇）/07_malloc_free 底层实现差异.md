# malloc/free 底层实现差异

## 一、前言

`malloc/free` 是 C 的通用内存分配接口，但"底层实现"并不是只有一个：

- Linux 默认是 glibc 的 **ptmalloc2**；
- 高性能场景常用 **jemalloc / tcmalloc / mimalloc**；
- 嵌入式/实时系统可能用固定块池、TLSF 等。

核心总纲：**接口相同，分配器不同；分配器决定碎片、并发性能和内存归还行为。** 理解 glibc 的实现，才能解释 RSS 不降、碎片、线程竞争。

## 二、glibc malloc 的核心结构

### 1. chunk

```text
+------------------+
| prev_size        |  前一块空闲时有效
+------------------+
| size | flags     |  大小 + 标志
+------------------+
| 用户数据          |
+------------------+
```

- 16 字节对齐；
- 最小 chunk 32 字节（64 位）；
- 标志位记录前块是否空闲、是否 mmap、是否属于非主 arena。

### 2. 分配路径

1. 查线程的 **tcache**（每线程 64 个大小类，最快）；
2. 查 **fastbins**（小块，不合并）；
3. 查 **smallbins / largebins**（按大小分类）；
4. 查 **unsorted bin**（刚释放、待归类）；
5. 从 **top chunk** 切；
6. top 不够 → `brk` 扩展（主 arena）或 `mmap` 新 arena。

### 3. 释放路径

1. 放入 tcache（如果没满）；
2. 否则根据大小进入 fastbin 或普通 bin；
3. 尝试与相邻空闲块合并（fastbin 延迟合并）；
4. 大块（超过 mmap 阈值）直接 `munmap` 归还。

### 4. arena

- 主 arena 用 `brk`；
- 线程 arena 用 `mmap`，数量上限约 `8 × CPU 核数`；
- 每个 arena 独立加锁，减少多线程竞争；
- arena 过多会让 RSS 上涨。

## 三、malloc 家族接口差异

| 接口 | 特点 |
|---|---|
| `malloc(n)` | 分配 n 字节，未初始化 |
| `calloc(n, size)` | 分配并清零，可能利用零页优化 |
| `realloc(p, n)` | 调整大小，可能移动并复制；失败返回 NULL，原指针仍有效 |
| `free(p)` | 释放；`free(NULL)` 安全 |
| `aligned_alloc(align, n)` | 按对齐分配（C11） |
| `posix_memalign(&p, align, n)` | POSIX 对齐分配 |
| `malloc_usable_size(p)` | glibc 扩展，返回实际可用大小（可能大于请求） |

常见错误：

- `realloc` 直接用返回值覆盖原指针，失败时丢失原指针；
- 对齐参数不是 2 的幂；
- 用 `malloc_usable_size` 的返回值当作请求大小做序列化（不可移植）。

## 四、free 的行为细节

- `free(NULL)` 安全；
- `free` 不改变调用者指针，需自行置空；
- 释放后内存进入 bin，内容可能保留（安全敏感数据应先清零）；
- 相邻块可能合并，合并会写 chunk 元数据；
- 大块 mmap 释放时直接 `munmap`；
- double free / invalid free 属于未定义行为，glibc 会尽量检测。

## 五、不同分配器的差异

| 分配器 | 特点 | 适用场景 |
|---|---|---|
| glibc ptmalloc2 | 默认，arena + tcache，通用 | 一般应用 |
| jemalloc | 多 arena、size class、低碎片，RSS 控制好 | 高并发服务、Redis 等 |
| tcmalloc | 线程缓存、小对象快，Google 系 | 高并发、短生命周期对象 |
| mimalloc | 轻量、低延迟、微软开源 | 通用高性能 |
| TLSF | O(1) 实时分配，碎片可控 | 嵌入式/实时系统 |

### 切换分配器

```bash
# 链接时替换
gcc app.c -ljemalloc -o app

# 运行时预加载
LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2 ./app
```

验证：

```bash
lsof -p <pid> | grep -E 'jemalloc|tcmalloc'
```

### 差异维度

- **碎片**：size class 设计不同，混合大小分配的碎片表现不同；
- **并发**：arena/线程缓存减少锁竞争；
- **RSS 归还**：有的分配器更积极 `madvise(MADV_DONTNEED)`；
- **可观测性**：jemalloc/tcmalloc 自带统计接口；
- **兼容性**：替换分配器要保证所有分配/释放都在同一分配器内完成，避免跨库混用。

## 六、malloc 调优参数

| 参数 | 作用 |
|---|---|
| `M_MMAP_THRESHOLD` | 大块走 mmap 的阈值 |
| `M_TRIM_THRESHOLD` | 堆顶空闲回收阈值 |
| `M_TOP_PAD` | brk 扩展余量 |
| `M_ARENA_MAX` / `MALLOC_ARENA_MAX` | arena 数量上限 |
| `MALLOC_PERTURB_` | free/alloc 时填充模式，暴露未初始化/悬空使用 |
| `MALLOC_CHECK_` | 堆一致性检查级别 |

```c
mallopt(M_MMAP_THRESHOLD, 256 * 1024);
mallopt(M_ARENA_MAX, 4);
```

## 七、常见问题

### 1. free 后 RSS 不降

- 小块留在 tcache/bin；
- arena 缓存；
- brk 堆未收缩；
- 碎片导致无法归还。

用 `malloc_trim(0)`、限制 arena、换分配器观察。

### 2. glibc 与第三方库分配器混用

库 A 用 jemalloc 分配，库 B 用 glibc free 释放，会崩溃。替换分配器必须全局一致（LD_PRELOAD 是进程级的，通常安全；静态链接混用要小心）。

### 3. realloc 后原指针

`realloc` 可能返回新地址，旧指针失效；失败返回 NULL 时旧指针仍有效。正确写法：

```c
void* tmp = realloc(p, n);
if (!tmp) { /* 处理失败，p 仍有效 */ }
p = tmp;
```

### 4. 内存未初始化

`malloc` 不保证清零（可能复用了旧数据）。需要清零用 `calloc` 或 `memset`。

### 5. 分配 0 字节

`malloc(0)` 可能返回 NULL 或一个可 free 的唯一指针，行为由实现定义。不要依赖。

## 八、面试标准简答

### 1. malloc 和 free 的底层做了什么？

glibc 的 malloc 维护 chunk、bin、arena 和 tcache，按大小走不同路径，必要时通过 brk/mmap 向内核申请内存；free 把块放回 bin，尝试合并，大块直接 munmap 归还。

### 2. malloc 分配的内存是物理内存吗？

不是。malloc 只返回虚拟地址并建立 VMA，第一次写入触发缺页才分配物理页。RSS 才反映实际驻留。

### 3. jemalloc/tcmalloc 和 glibc malloc 有什么区别？

它们在 size class、线程缓存、arena 设计和内存归还策略上不同，通常在高并发、低碎片、RSS 控制方面更优；替换时要保证全进程使用同一分配器。

### 4. realloc 会移动内存吗？

可能。空间不足或需要整理时会分配新块、复制数据、释放旧块。返回值可能是新地址，失败返回 NULL 且原块保持有效。

## 九、极简口诀

**malloc 管 bin/arena，brk/mmap 向内核要；**

**小块 tcache 最快，大块 mmap 直接还；**

**calloc 清零、realloc 可能搬家；**

**free 不置空、不保证还 RSS。**

## 相关文档

- 《heap 堆空间分配与内核交互机制》（04 程序加载与运行机制，brk/mmap 与缺页）

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
