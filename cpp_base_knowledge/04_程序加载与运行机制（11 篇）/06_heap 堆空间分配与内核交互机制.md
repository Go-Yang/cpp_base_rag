# heap 堆空间分配与内核交互机制

## 一、前言

堆是程序运行时动态申请内存的区域。`malloc` / `new` 看起来是"向系统要内存"，实际上要经过三层：

1. 语言层：`new` → `operator new` → `malloc`；
2. 分配器层：glibc `malloc` 管理空闲块、bin、arena；
3. 内核层：`brk` / `mmap` 扩展地址空间，缺页时才分配物理页。

核心总纲：**malloc 管用户态内存池，brk/mmap 管向内核要地，缺页才真正给物理内存。** 理解这三层，才能解释"free 了内存为什么 RSS 不降"。

## 二、brk/sbrk 机制

### 1. 程序断点

- `brk` 指向堆的当前末尾（program break）；
- `sbrk(n)` 把断点移动 n 字节，返回旧断点；
- 堆 VMA 是 `[heap]`，向高地址增长；
- 小块分配通常来自 brk 堆。

```c
void* old = sbrk(0);      // 获取当前断点
sbrk(4096);               // 扩展 4KB
```

### 2. 特点

- 扩展/收缩是连续的，只能在堆顶操作；
- 释放中间的内存不能直接还给内核，只能留给 malloc 复用；
- 多线程下 brk 是全局资源，需要加锁，所以 glibc 用多 arena 缓解竞争。

## 三、mmap 机制

### 1. 大块分配走 mmap

glibc 默认阈值 `M_MMAP_THRESHOLD` 为 128KB：

- 小于阈值：brk 堆分配；
- 大于等于阈值：`mmap` 匿名映射，独立 VMA；
- `free` 时大块直接 `munmap` 还给内核。

阈值会动态调整：释放大块后可能提高阈值，避免频繁 mmap/munmap，最高到 32MB。

### 2. mmap 匿名映射

```c
void* p = mmap(NULL, size, PROT_READ | PROT_WRITE,
               MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
```

- `MAP_ANONYMOUS`：不对应文件，内容初始为 0；
- `MAP_PRIVATE`：写时复制；
- 分配后只是 VMA，第一次写入才分配物理页。

### 3. brk 与 mmap 对比

| 维度 | brk | mmap |
|---|---|---|
| 增长方式 | 连续堆顶 | 独立映射区 |
| 适用大小 | 小块 | 大块 |
| 释放归还 | 通常不归还，留在 arena | `munmap` 直接归还 |
| 碎片 | 易产生 | 较少 |
| 线程竞争 | 全局锁 | 各自映射 |

## 四、glibc malloc 的内部结构

### 1. chunk

每个分配块有元数据头：

```text
+------------------+
| prev_size        |  前一块空闲时才有
+------------------+
| size + flags     |  块大小 + 标志位
+------------------+
| 用户数据 ...      |
+------------------+
```

- 大小按 16 字节对齐（64 位）；
- 最小 chunk 32 字节；
- 标志位记录前一块是否空闲、是否 mmap 分配等。

### 2. bin

空闲 chunk 按大小分类：

- **tcache**：每线程 64 个单链表，最快路径；
- **fastbins**：小块，不合并；
- **smallbins**：小尺寸，双向链表；
- **largebins**：大尺寸，按大小分桶；
- **unsorted bin**：刚释放、待归类的块。

分配时先查 tcache，再 fastbins/smallbins，最后 largebins 和 top chunk。

### 3. arena

- 每个线程可能绑定一个 arena，减少锁竞争；
- arena 数量上限约 `8 * CPU 核数`（64 位）；
- 每个 arena 有自己的堆和 bin；
- 线程数多、分配频繁时，arena 会增多，RSS 可能上涨。

### 4. top chunk

堆顶的空闲块叫 top chunk。分配时如果 bin 里没有合适的块，就从 top chunk 切；top 不够就 `brk` 扩展。

### 5. 合并

`free` 时，如果相邻块空闲，会合并（fastbins 除外），减少碎片。合并后的大块可能进入 unsorted bin，等待再分配。

## 五、free 之后内存去哪了

### 1. 不一定还给内核

- 小块 `free` 后进入 tcache/bin，留在 arena 里复用；
- 大块（mmap）`free` 时 `munmap` 直接归还；
- brk 堆顶的大空闲块可能通过 `malloc_trim` 收缩。

所以：

- 内存泄漏表现为 RSS 持续上涨；
- 大量分配释放后 RSS 不降，可能只是分配器缓存，不一定是泄漏。

```c
malloc_trim(0);    // 主动归还 brk 顶部的空闲内存
```

### 2. 环境变量与 mallopt

| 参数 | 作用 |
|---|---|
| `M_MMAP_THRESHOLD` | 超过该大小走 mmap |
| `M_TRIM_THRESHOLD` | 堆顶空闲超过该值则收缩 |
| `M_TOP_PAD` | 每次 brk 扩展的额外余量 |
| `M_ARENA_MAX` | arena 数量上限 |
| `MALLOC_ARENA_MAX` | 环境变量，限制 arena |

```bash
MALLOC_ARENA_MAX=2 ./app
```

## 六、虚拟内存与物理内存

### 1. 按需分页

`malloc` 返回的地址只是虚拟地址，第一次写入才触发缺页，内核分配物理页：

- 匿名页初始为 0；
- 分配 1GB 不等于立即占 1GB 物理内存；
- RSS 反映实际驻留页。

### 2. overcommit

Linux 默认允许 overcommit，`malloc` 可能成功但真正写入时触发 OOM Killer。

```bash
cat /proc/sys/vm/overcommit_memory
# 0 启发式，1 总是允许，2 严格限制
```

### 3. 内存回收

- 匿名页不能直接丢弃，需 swap；
- 文件页可回收；
- 内存紧张时触发直接回收、kswapd、OOM。

## 七、常见问题

### 1. 内存泄漏

分配后未释放，RSS 持续上涨。工具：

- Valgrind `--leak-check=full`；
- ASAN `-fsanitize=address`；
- heaptrack、massif；
- `mtrace`、`malloc_stats`、`mallinfo2`。

### 2. 双重释放

同一指针 `free` 两次，破坏 bin 链表，可能崩溃或被利用。ASAN/Valgrind 可定位。

### 3. use-after-free

释放后继续访问，内容可能已被复用。ASAN 的 quarantine 和 Valgrind 能检测。

### 4. 堆溢出

写越界破坏相邻 chunk 的元数据，`free` 时报 `corrupted size vs. prev_size`、`munmap_chunk(): invalid pointer`。ASAN 可精确定位。

### 5. 内存碎片

频繁分配不同大小的块，导致大量小空闲块无法满足大请求，RSS 高但可用内存少。缓解：对象池、固定大小分配器、jemalloc/tcmalloc。

### 6. RSS 不降

可能是 arena/tcache 缓存、碎片、未归还的 brk 堆。用 `malloc_trim`、限制 arena、或换分配器。

## 八、排查命令

| 目的 | 命令 |
|---|---|
| 查看堆内存 | `cat /proc/<pid>/smaps | grep -A20 heap` |
| 查看 malloc 统计 | `malloc_stats()` / `mallinfo2()` |
| 限制 arena | `MALLOC_ARENA_MAX=2` |
| 主动归还 | `malloc_trim(0)` |
| 泄漏检测 | `valgrind --leak-check=full` |
| ASAN | `-fsanitize=address -g` |
| 跟踪分配 | `mtrace()` + `MALLOC_TRACE` |
| 堆剖析 | heaptrack / massif |

## 九、面试标准简答

### 1. brk 和 mmap 的区别？

brk 扩展连续的堆顶，适合小块，释放后通常不归还内核；mmap 建立独立匿名映射，适合大块，释放时 munmap 直接归还。glibc 默认以 128KB 为阈值切换。

### 2. malloc 申请的内存是物理内存吗？

不是。malloc 只返回虚拟地址，内核建立 VMA；第一次写入触发缺页才分配物理页。所以 VSZ 远大于 RSS，overcommit 下还可能被 OOM Killer 杀掉。

### 3. free 之后内存会还给操作系统吗？

不一定。小块进入 tcache/bin 留在 arena 复用；mmap 大块直接 munmap 归还；brk 堆顶的空闲块可通过 malloc_trim 收缩。RSS 不降不一定是泄漏。

### 4. 什么是内存碎片？

已释放的小块分散在堆中，无法拼成大块满足新的大请求，导致总空闲内存足够但分配失败或 RSS 偏高。可用对象池、固定大小分配、jemalloc/tcmalloc 缓解。

## 十、极简口诀

**malloc 管池，brk/mmap 要地，缺页才给物理页；**

**小走 brk，大走 mmap，128K 是默认界；**

**free 不一定还内核，tcache/bin 留着复用；**

**泄漏看 RSS，ASAN/Valgrind 定位。**

## 相关文档

- 《malloc_free 底层实现差异》（05 资源管理与内存问题，glibc/分配器实现对比）

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
