# GDB 完整调试命令体系与实战流程

## 一、前言

GDB 是 Linux 下最常用的调试器，核心能力：

- 启动/附加进程；
- 设置断点、单步执行；
- 查看变量、寄存器、内存、调用栈；
- 分析 CoreDump；
- 调试多线程、信号、动态库。

核心总纲：**GDB 的工作流是"停下来 → 看现场 → 单步/继续"。** 先定位崩溃或异常点，再回溯调用栈和变量，不要一上来就单步。

## 二、启动方式

```bash
gdb ./app                          # 启动并停在 main 之前
gdb --args ./app arg1 arg2         # 带参数
gdb -p <pid>                       # attach 运行中的进程
gdb ./app core                     # 分析 core
gdb -ex run -ex bt --batch ./app   # 批处理
```

编译时加调试信息：

```bash
gcc -g -Og app.c -o app            # 推荐 -Og，兼顾调试和优化
gcc -g -O0 app.c -o app            # 完全不优化，变量最准确
```

## 三、断点

### 1. 基本断点

```gdb
break main                 # 函数
break foo.c:42             # 文件:行号
break *0x401234            # 地址
tbreak foo                 # 临时断点，命中一次后删除
rbreak ^foo_               # 正则匹配函数
```

### 2. 条件断点

```gdb
break foo.c:42 if x > 100
condition 1 x == 0
ignore 1 10                # 前 10 次不中断
```

### 3. 观察点

```gdb
watch x                    # 写 x 时中断
rwatch x                   # 读 x 时中断
awatch x                   # 读写都中断
watch *(int*)0x7fffffffe000
```

观察点依赖硬件/软件监视，变量必须在作用域内，且执行很慢。

### 4. 捕获点

```gdb
catch throw                # C++ 异常抛出
catch syscall openat       # 系统调用
catch signal SIGSEGV
```

## 四、执行控制

| 命令 | 作用 |
|---|---|
| `run` / `r` | 重新运行 |
| `continue` / `c` | 继续到下一个断点 |
| `next` / `n` | 单步，不进入函数 |
| `step` / `s` | 单步，进入函数 |
| `finish` | 执行到当前函数返回 |
| `until` | 执行到当前行之后/指定位置 |
| `advance foo.c:50` | 运行到指定行 |
| `jump` | 跳转到指定位置（慎用） |
| `return` | 强制当前函数返回 |
| `kill` | 终止被调试进程 |

## 五、查看现场

### 1. 调用栈

```gdb
bt                 # backtrace
bt full            # 带局部变量
frame 2            # 切换到第 2 帧
up / down          # 上下移动
info frame         # 当前帧详情
```

### 2. 变量与表达式

```gdb
print x
print *p
print arr[0]@10          # 打印 10 个元素
ptype Foo                # 类型定义
info locals
info args
set var x = 42
call foo(1, 2)
```

### 3. 寄存器与内存

```gdb
info registers
p $pc
p $rsp
x/16gx $rsp              # 16 个 8 字节十六进制
x/10i $pc                # 反汇编 10 条
x/s 0x...                # 字符串
```

### 4. 源与汇编

```gdb
list
list foo.c:1,50
disassemble /m main      # 带源码
info line *0x401234
```

### 5. 线程

```gdb
info threads
thread 2
thread apply all bt
set scheduler-locking on # 只让当前线程跑
```

## 六、信号处理

```gdb
handle SIGSEGV stop print
handle SIGPIPE nostop noprint pass
signal SIGUSR1
info signals
```

默认情况下，GDB 会拦截 SIGSEGV 等信号，方便看现场；`pass` 可以让信号继续传给程序。

## 七、动态库与符号

```gdb
info sharedlibrary
sharedlibrary libfoo
set solib-search-path /path/to/libs
info symbol 0x7ffff7a0d000
```

符号缺失时：

- 确认二进制带 `-g`；
- 确认加载的是正确的库版本；
- 用 `set debug-file-directory`、build-id 查找调试文件；
- `strip` 过的程序需要单独 `.debug` 文件。

## 八、实用技巧

### 1. .gdbinit

```gdb
set pagination off
set print pretty on
set print elements 0
set history save on
```

### 2. 日志

```gdb
set logging file gdb.log
set logging on
```

### 3. 脚本化

```bash
gdb -batch -ex 'break main' -ex run -ex bt ./app
```

### 4. TUI

```gdb
tui enable
layout src
layout asm
```

## 九、典型实战流程

### 1. 崩溃分析

```bash
gdb ./app core
(gdb) bt
(gdb) frame 0
(gdb) info registers
(gdb) x/i $pc
(gdb) p $_siginfo
```

### 2. 死锁

```bash
gdb -p <pid>
(gdb) thread apply all bt
```

查看每个线程卡在哪个锁上。

### 3. 变量被改坏

```gdb
watch x
continue
bt
```

定位第一次写坏的位置。

### 4. 条件复现

```gdb
break process if id == 42
```

## 十、常见问题

### 1. 断点打不上

- 程序未加载（先 `start` 或 `break main` 后 `run`）；
- 优化导致行号映射不准（用 `-Og`/`-O0`）；
- 符号缺失（检查 `-g`、`file`、`info sources`）。

### 2. 变量显示 optimized out

优化把变量放进了寄存器或消除。用 `-Og`，或看汇编/寄存器。

### 3. bt 显示 ???

缺少符号或栈被破坏。检查库符号、栈溢出、帧指针。

### 4. attach 失败

权限不足（ptrace_scope）、进程已退出、容器 PID 命名空间不同。

## 十一、面试标准简答

### 1. GDB 常用调试流程？

编译加 `-g`，启动/attach/core 进入，设置断点或直接 `bt` 看崩溃现场，检查调用栈、变量、寄存器、内存，再单步或条件断点定位根因。

### 2. next 和 step 的区别？

`next` 单步执行但不进入函数调用；`step` 会进入被调函数。`finish` 执行到当前函数返回。

### 3. watch 和 break 的区别？

`break` 在代码位置中断；`watch` 在变量被写入时中断，适合定位"变量被谁改坏"。watch 依赖硬件/软件监视，开销较大。

### 4. 如何分析 CoreDump？

`gdb ./app core`，先 `bt` 看崩溃调用栈，`info registers` 看故障地址和指令，结合源码、反汇编、`/proc/maps` 还原现场。需要匹配的二进制和调试符号。

## 十二、极简口诀

**-g 编译再调试，run/attach/core 三入口；**

**break 定点、watch 盯变量，bt 看栈；**

**next 不进、step 进，finish 到返回；**

**info registers 看现场，x/i 看指令。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
