# text 代码段底层特性与运行机制

## 一、前言

`.text` 是存放机器指令的段。它看起来"只是代码"，但它的只读、可执行、可共享、可回收等特性，直接决定了程序的安全性、内存占用和调试方式。

核心总纲：**text 是只读可执行的干净文件页，多进程共享、按需加载、可被回收；写 text 必崩，改代码需 mprotect。** 理解 text 是理解 W^X、PIE、JIT、text relocation 的基础。

## 二、text 的 ELF 属性

### 1. section 属性

```bash
readelf -S app | grep -E '\.text|\.rodata'
```

`.text` 的 `sh_flags` 通常包含：

- `ALLOC`：加载进内存；
- `EXECINSTR`：可执行；
- 不含 `WRITE`：只读。

### 2. segment 属性

`PT_LOAD` 中代码段的 `p_flags` 是 `R E`（读 + 执行）。内核映射时使用 `PROT_READ | PROT_EXEC`，写入会触发 `SIGSEGV`。

```bash
readelf -l app | grep -A2 LOAD
```

### 3. 与 .rodata 的区别

- `.text`：指令，可执行；
- `.rodata`：常量、字符串字面量，只读但不可执行；
- 两者通常被放在同一个只读 `PT_LOAD` 或多个相邻段中。

## 三、text 的运行特性

### 1. 文件页共享

同一可执行文件启动多个进程时，`.text` 映射到**同一份物理页**（page cache）：

- 多个进程共享代码，省内存；
- 页面干净（clean），内存紧张时可直接回收，不需要写回；
- 下次访问再从文件读取。

这是动态链接和同一程序多实例省内存的基础。

### 2. 按需分页

程序启动时不会把整个 `.text` 读进内存，只建立映射。执行到哪一页，缺页时才从文件读入。所以：

- 冷启动第一段代码会触发缺页；
- 热代码常驻，冷代码可能被回收；
- 大程序的 `.text` 不会一次性占满内存。

### 3. 位置无关与 ASLR

PIE 可执行文件和共享库的代码使用位置无关寻址（RIP 相对 + GOT/PLT），加载基址随机化后仍能正确运行。非 PIE 程序代码地址固定，ASLR 对其代码段无效。

### 4. 指令缓存

CPU 有独立的指令缓存（I-Cache）。正常程序不需要关心，但**自修改代码/JIT** 修改指令后必须保证缓存一致性：

- x86 的 I-Cache 与 D-Cache 基本一致，通常不需要显式刷新；
- ARM/AArch64 需要 `__builtin___clear_cache` 或系统调用清理；
- 多核场景还需要内存屏障和核间同步。

## 四、写 text 会发生什么

```c
char* p = (char*)main;   // 指向代码段
*p = 0x90;               // 写入只读页
```

运行结果：`SIGSEGV`（Segmentation fault），因为页表权限是只读。

如果确实要改（自修改代码、热补丁、JIT）：

```c
#include <sys/mman.h>
#include <unistd.h>

long page = sysconf(_SC_PAGESIZE);
void* addr = (void*)((uintptr_t)target & ~(page - 1));

mprotect(addr, page, PROT_READ | PROT_WRITE | PROT_EXEC);  // 临时可写
memcpy(target, new_code, size);
__builtin___clear_cache(target, target + size);            // 非 x86 必须
mprotect(addr, page, PROT_READ | PROT_EXEC);               // 恢复只读可执行
```

现代安全策略通常禁止同时可写可执行（W^X），更推荐"先写后改权限"：映射 RW → 写入 → `mprotect` 为 RX → 执行。

## 五、JIT 与可执行内存

JIT 编译器需要生成机器码并执行，典型流程：

1. `mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)`；
2. 写入生成的指令；
3. `mprotect(addr, size, PROT_READ | PROT_EXEC)`；
4. 通过函数指针调用；
5. 卸载时 `munmap`。

安全加固环境（SELinux、PaX、iOS/Android）可能限制 `PROT_EXEC` 的匿名映射，需要特殊处理或使用系统提供的 JIT 接口。

## 六、PLT/GOT 与 text

- `.plt` 是可执行段，存放外部函数调用的跳板；
- `.got` / `.got.plt` 是可写数据段，存放函数/变量地址；
- 惰性绑定第一次调用会修改 GOT，所以 GOT 必须可写；
- `-Wl,-z,relro,-z,now` 可以把 GOT 在启动后设为只读，防止 GOT 劫持。

```bash
readelf -S app | grep -E '\.plt|\.got'
objdump -d -j .plt app
```

## 七、text relocation

共享库如果没有用 `-fPIC` 编译，代码里可能包含需要运行时修改的绝对地址，产生 **text relocation**：

```text
warning: relocation against ... in read-only section '.text'
```

问题：

- 代码段必须临时改成可写，破坏共享；
- 加载器可能拒绝加载；
- 安全策略不允许。

修复：所有参与共享库的源文件和静态库都用 `-fPIC` 重新编译。

```bash
readelf -d libfoo.so | grep TEXTREL   # 有输出说明存在 text relocation
```

## 八、text 的优化与裁剪

### 1. 函数级分段与回收

```bash
gcc -ffunction-sections -fdata-sections -Wl,--gc-sections ...
```

每个函数/变量单独成段，链接器删除未被引用的段，减小体积。注意：注册表、中断向量等要用 `KEEP` 保护。

### 2. 热冷分离

编译器可以把冷函数放到 `.text.unlikely`，或用 `__attribute__((cold))` 提示，提升 I-Cache 局部性。

### 3. 对齐与页边界

函数/循环对齐可以提升取指效率；过度对齐会增大体积。`-falign-functions`、`-falign-loops` 可调。

## 九、调试与排查

| 目的 | 命令 |
|---|---|
| 反汇编 | `objdump -d app` |
| 反汇编指定函数 | `objdump -d --disassemble=main app` |
| gdb 反汇编 | `disassemble /m main` |
| 查看 text 段 | `readelf -S app | grep text` |
| 查看权限 | `readelf -l app | grep -A1 LOAD` |
| 地址转源码行 | `addr2line -e app -f -C 0x...` |
| 检查 text relocation | `readelf -d libfoo.so | grep TEXTREL` |
| 检查可执行栈 | `readelf -l app | grep GNU_STACK` |

## 十、常见问题

### 1. 为什么修改字符串字面量会崩

```c
char* s = "hello";
s[0] = 'H';     // 字符串在 .rodata，只读页 → SIGSEGV
```

正确写法：`char s[] = "hello";`，数组在栈上可写。

### 2. 函数指针指向的地址每次运行不同

PIE + ASLR。用 `setarch -R` 或 gdb 关闭随机化后再对比地址。

### 3. warning: executable stack

`PT_GNU_STACK` 标记栈可执行，通常由汇编文件缺少 `.note.GNU-stack` 节导致。用 `-Wa,--noexecstack` 或补标记修复。

### 4. 为什么 .text 可以多进程共享，.data 不行

`.text` 只读、干净、文件页，天然可共享；`.data` 可写，写入需要 COW，每个进程最终有独立副本。

## 十一、面试标准简答

### 1. 为什么 .text 段是只读的？

防止程序意外或恶意修改指令，保证代码完整性和多进程共享安全。写入只读页会触发 SIGSEGV。需要自修改/JIT 时必须显式 `mprotect`。

### 2. 多个进程如何共享同一份代码？

同一可执行文件/共享库的 `.text` 是文件页，页表把不同进程的虚拟地址映射到同一物理页；只读且干净，内核可以直接共享和回收。

### 3. PIE 和 text 有什么关系？

PIE 让代码使用位置无关寻址，可以被加载到任意基址，从而支持 ASLR。非 PIE 代码地址固定，代码段不随机化。

### 4. JIT 如何执行生成的代码？

先用 `mmap` 申请可写匿名内存，写入机器码，再 `mprotect` 为可读可执行，最后通过函数指针调用。遵守 W^X，避免同时可写可执行。

## 十二、极简口诀

**text 只读又执行，多进程共享文件页；**

**写代码段必 SIGSEGV，改代码先 mprotect；**

**JIT 先写后改权，W^X 要遵守；**

**PIC 避免 text relocation，gc-sections 裁冷码。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
