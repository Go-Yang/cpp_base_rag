# CoreDump 堆栈解析完整排错流程

## 一、前言

拿到 core 后，GDB 的第一任务不是"看代码"，而是回答四个问题：

1. 进程收到什么信号？
2. 崩溃时执行到哪条指令？
3. 访问了哪个地址？为什么非法？
4. 调用栈是什么？是谁走到这里的？

核心总纲：**信号 → 故障地址 → 指令 → 调用栈 → 源码。** 按这个顺序，能在几分钟内从 core 定位到根因。

## 二、打开 core

```bash
gdb ./app core
# 或
gdb -batch -ex 'bt full' -ex 'info registers' ./app core
```

前提：

- 二进制必须是崩溃时的同一版本；
- 最好带 `-g` 调试信息；
- 版本不匹配会导致栈和行号错乱。

```bash
readelf -n app | grep 'Build ID'
readelf -n core | grep 'Build ID'
```

## 三、第一步：看信号

```gdb
(gdb) info program
(gdb) p $_siginfo.si_signo
(gdb) p $_siginfo
```

常见信号：

| 信号 | 含义 |
|---|---|
| SIGSEGV | 非法内存访问（空指针、越界、写只读页） |
| SIGBUS | 总线错误（未对齐访问、映射文件截断） |
| SIGABRT | `abort`、断言失败、堆检测报错 |
| SIGILL | 非法指令 |
| SIGFPE | 算术异常（除零、整数溢出陷阱） |
| SIGSYS | 非法系统调用（seccomp） |

## 四、第二步：看故障指令和地址

```gdb
(gdb) bt
(gdb) frame 0
(gdb) info registers rip rsp rbp
(gdb) x/i $pc
(gdb) disassemble $pc-16,$pc+16
```

### 1. SIGSEGV 的故障地址

```gdb
(gdb) p $_siginfo._sifields._sigfault.si_addr
```

典型判断：

- `0x0`：空指针解引用；
- `0x8`、`0x10` 等小偏移：访问空指针的成员；
- 接近栈保护页：栈溢出；
- 只读页地址：写 `.text` / `.rodata`；
- 未映射地址：野指针/悬空指针。

### 2. 看该地址属于哪个映射

core 里的映射信息：

```gdb
(gdb) info proc mappings
(gdb) info files
```

运行中的进程可以用 `/proc/<pid>/maps`。权限是否匹配（r-x/rw-）能解释为什么触发 SIGSEGV。

## 五、第三步：看调用栈

```gdb
(gdb) bt
(gdb) bt full
(gdb) thread apply all bt
```

### 1. 栈被破坏

如果 `bt` 显示 `???`、重复帧或直接失败：

- 栈缓冲区溢出覆盖了返回地址；
- 栈指针错误；
- 缺少帧指针（`-fomit-frame-pointer`）；
- 二进制/符号不匹配。

尝试：

```gdb
(gdb) info frame
(gdb) x/64gx $rsp
(gdb) set backtrace past-main on
(gdb) set backtrace past-entry on
```

`x/64gx $rsp` 手动扫描栈，寻找像返回地址的值，再用 `info symbol` 判断。

### 2. 常见模式

| 栈顶特征 | 可能原因 |
|---|---|
| `malloc` / `free` 内部 | 堆元数据被破坏、double free |
| `__stack_chk_fail` | 栈缓冲区溢出 |
| `pthread_mutex_lock` | 死锁或锁被破坏 |
| `std::terminate` | 未捕获异常、thread 未 join |
| `abort` / `assert` | 断言失败、主动终止 |
| 递归函数大量重复 | 栈溢出 |

## 六、第四步：源码定位

```gdb
(gdb) frame 1
(gdb) list
(gdb) info locals
(gdb) info args
(gdb) p *ptr
```

结合 `addr2line`：

```bash
addr2line -e app -f -C -i 0x...
```

## 七、常见崩溃类型与处理方法

### 1. 空指针

```text
si_addr = 0x0
```

检查指针来源：未初始化、返回值未判空、回调传 NULL。

### 2. 野指针/悬空指针

`si_addr` 是随机或已释放地址。用 ASAN 复现，或检查 `free` 后的使用。

### 3. 栈溢出

`rsp` 接近栈底保护页，`bt` 有大量递归帧。检查递归终止条件、大局部数组、线程栈大小。

### 4. 堆损坏

崩溃在 `malloc/free` 内部，`si_signo = SIGABRT`，信息类似 `free(): invalid pointer`。用 ASAN/Valgrind 重新跑。

### 5. 写只读内存

`si_addr` 属于 `r--` 或 `r-x` 映射（`.rodata`/`.text`）。检查是否修改字符串字面量、常量或代码段。

### 6. 未对齐访问（SIGBUS）

ARM/SPARC 等架构上，访问未对齐地址会触发 SIGBUS。检查 `packed` 结构体、指针转换。

## 八、符号与调试文件

### 1. 缺少符号

```bash
file app
readelf -S app | grep debug
```

- 程序被 strip：需要单独的 `.debug` 文件；
- 库版本不对：用 build-id 查找；
- 容器里的二进制与 core 不匹配。

### 2. debuginfod

```bash
export DEBUGINFOD_URLS="https://debuginfod.elfutils.org/"
gdb ./app core
```

GDB/elfutils 可以按 build-id 自动下载调试信息（需要网络）。

## 九、标准排错流程

1. `gdb app core`；
2. `info program` / `p $_siginfo` 看信号；
3. `bt` 看栈，`frame 0` 看崩溃点；
4. `x/i $pc` 看指令，`info registers` 看寄存器；
5. 取故障地址，对照 `info proc mappings`；
6. `bt full` + `info locals/args` 查变量；
7. `addr2line` 或 `list` 定位源码；
8. 用 ASAN/Valgrind 复现验证；
9. 修复并加回归测试。

## 十、面试标准简答

### 1. 拿到 core 后第一步做什么？

先看信号和崩溃点：`bt`、`info registers`、`x/i $pc`，再用 `$_siginfo` 取故障地址，对照内存映射判断是空指针、越界、写只读页还是栈溢出。

### 2. bt 显示 ??? 怎么办？

可能栈被破坏、缺少符号或帧指针。检查二进制版本/调试信息，用 `info frame`、`x/64gx $rsp` 手动扫描，或用 `set backtrace past-main on`。

### 3. 如何判断是栈溢出还是堆损坏？

栈溢出通常 `rsp` 接近栈保护页、`bt` 有大量递归帧或 `__stack_chk_fail`；堆损坏通常崩溃在 `malloc/free`，伴随 `SIGABRT` 和堆检测信息。

### 4. core 和二进制版本不匹配会怎样？

栈帧、行号、变量全部错位，可能得到完全错误的结论。用 build-id 确认匹配，保留发布版本的二进制和调试文件。

## 十一、极简口诀

**先看信号再看址，x/i 看指令；**

**bt 看调用栈，mappings 判权限；**

**空指针小偏移，栈溢出近 guard；**

**堆坏在 free，ASAN 复现快。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
