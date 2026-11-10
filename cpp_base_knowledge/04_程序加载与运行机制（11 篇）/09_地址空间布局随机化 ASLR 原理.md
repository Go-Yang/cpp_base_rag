# 地址空间布局随机化 ASLR 原理

## 一、前言

ASLR（Address Space Layout Randomization，地址空间布局随机化）让程序每次启动时，栈、堆、共享库、可执行文件的加载地址都不同。

它的目的不是"让程序更稳定"，而是**提高漏洞利用难度**：攻击者无法在编写 exploit 时写死跳转地址、ROP gadget 地址或 shellcode 地址。

核心总纲：**ASLR 随机化的是"基址"，不是"内容"；只有 PIE 才能随机化可执行文件自身的代码段。**

## 二、ASLR 随机化哪些区域

Linux 上主要随机化：

| 区域 | 是否随机 | 说明 |
|---|---|---|
| 主线程栈 | 是 | 栈顶地址随机偏移 |
| mmap 区（共享库、线程栈、匿名映射） | 是 | mmap 基址随机 |
| 堆（brk） | 是（完全 ASLR） | 堆起始地址随机 |
| PIE 可执行文件 | 是 | 整个映像基址随机 |
| 非 PIE 可执行文件 | 否 | 代码段固定在 0x400000 附近 |
| vDSO / vvar | 是 | 内核映射位置随机 |
| 内核空间 | 内核 KASLR | 与用户态 ASLR 独立 |

注意：非 PIE 程序的 **代码地址固定**，只有栈、堆、库随机。所以攻击者可用的固定 gadget 仍然存在。

## 三、内核控制开关

```bash
cat /proc/sys/kernel/randomize_va_space
```

| 值 | 含义 |
|---|---|
| 0 | 关闭 ASLR |
| 1 | 保守随机化（共享库、栈、mmap、vDSO） |
| 2 | 完全随机化（额外随机化 brk 堆） |

临时修改：

```bash
sudo sysctl -w kernel.randomize_va_space=0
```

## 四、随机化实现（概念）

以 x86-64 为例：

1. 内核在 `execve` 时生成随机偏移；
2. 栈顶：在合法范围内随机下移，同时留出 `RLIMIT_STACK` 空间；
3. mmap 基址：在用户空间高段随机选择，共享库依次向下映射；
4. PIE 可执行文件：选择一个随机基址加载；
5. 堆：从 `.bss` 之后随机偏移开始；
6. vDSO/vvar：在 mmap 区随机选择。

随机熵（位数）随架构和内核版本不同：x86-64 的 mmap 随机化通常有 28 位左右，栈约 22 位。32 位系统熵更小，容易被暴力破解。

## 五、PIE：可执行文件也能随机

### 1. 编译选项

```bash
gcc -fPIE -pie main.c -o app      # 显式 PIE
gcc -no-pie main.c -o app         # 非 PIE
```

现代发行版通常默认 PIE，`file` 显示：

```text
app: ELF 64-bit LSB pie executable, x86-64, ...
```

### 2. 与 ASLR 的关系

- PIE 可执行文件是 `ET_DYN`，可以被加载到随机基址；
- 非 PIE 是 `ET_EXEC`，链接时地址固定，ASLR 无法移动它；
- 共享库天然是 `ET_DYN`，总是随机（只要 ASLR 开启）。

### 3. 代价

- 代码必须位置无关（RIP 相对 + GOT/PLT）；
- 少量性能开销（通常可忽略）；
- 调试时地址每次都变。

## 六、关闭 ASLR 调试

```bash
# 只对当前命令关闭
setarch "$(uname -m)" -R ./app

# gdb 默认关闭随机化（可配置）
gdb ./app
(gdb) set disable-randomization on
```

C 代码方式：

```c
#include <sys/personality.h>
personality(ADDR_NO_RANDOMIZE);
```

关闭后地址稳定，方便对照 core、gdb 和反汇编。

## 七、ASLR 与其他防护的关系

现代二进制防护是组合拳：

| 防护 | 防什么 |
|---|---|
| ASLR + PIE | 地址不可预测，阻止硬编码跳转 |
| NX（DEP） | 数据页不可执行，阻止 shellcode |
| Stack Canary | 检测栈缓冲区溢出 |
| RELRO | 保护 GOT 不被改写 |
| FORTIFY_SOURCE | 检测常见缓冲区操作错误 |
| CFI / CET | 限制控制流劫持 |
| seccomp | 限制系统调用 |

ASLR 单独并不够：如果存在信息泄漏（打印指针、格式化字符串、越界读），攻击者可以算出基址，ASLR 就被绕过。

## 八、ASLR 的局限

1. **信息泄漏可绕过**：泄露一个库地址即可推算基址；
2. **32 位熵不足**：可用地址空间小，可能被暴力枚举；
3. **非 PIE 程序代码固定**：仍可做 ROP；
4. **fork 后子进程布局相同**：多进程服务可能共享同一布局；
5. **内核 KASLR 与用户态 ASLR 独立**：配置不当可能泄露；
6. **JIT/自映射内存**：某些运行时需要可执行内存，可能削弱 W^X。

它不是"安全银弹"，只是提高利用门槛。

## 九、排查与实验

### 1. 观察地址变化

```bash
for i in $(seq 5); do
  ./app &
  pid=$!
  grep -E 'stack|libc' /proc/$pid/maps | head -3
  wait $pid
done
```

每次输出的地址应该不同。

### 2. 查看随机化开关

```bash
cat /proc/sys/kernel/randomize_va_space
```

### 3. 对比 PIE / 非 PIE

```bash
gcc -no-pie app.c -o app_fixed
gcc -fPIE -pie app.c -o app_pie
file app_fixed app_pie
```

运行后看 `readelf -h` 的 Entry 是否变化（非 PIE 固定，PIE 随基址变化）。

### 4. 崩溃地址不稳定

ASLR 开启时，每次崩溃地址不同；用 `setarch -R` 或 core + gdb 分析时注意加载基址。

## 十、常见问题

### 1. 为什么同样的崩溃每次地址不同

ASLR 随机化了栈、库、PIE 基址。用 `setarch -R` 关闭后复现固定地址，或根据 `/proc/pid/maps` 计算偏移。

### 2. 为什么 PIE 程序反汇编地址和运行时地址差很多

反汇编显示的是相对基址的偏移，运行时真实地址 = 加载基址 + 偏移。用 `info proc mappings` 查基址。

### 3. 为什么关闭 ASLR 后漏洞还能利用

关闭 ASLR 只是让地址固定；NX、canary、RELRO 等防护仍可能阻止利用。反过来，开启 ASLR 也不能阻止信息泄漏后的利用。

### 4. 容器里 ASLR 生效吗

默认生效；但容器共享内核，`randomize_va_space` 是内核级设置。某些运行时/沙箱可能通过 personality 关闭。

## 十一、面试标准简答

### 1. ASLR 随机化了哪些区域？

栈、mmap 区（共享库、线程栈、匿名映射）、brk 堆、PIE 可执行文件基址、vDSO/vvar。非 PIE 可执行文件的代码段地址固定，不随机化。

### 2. PIE 和 ASLR 的关系？

PIE 让可执行文件成为位置无关的 `ET_DYN`，从而可以被加载到随机基址；ASLR 是内核的随机化机制。没有 PIE，ASLR 只能随机化栈、堆和库，无法随机化程序自身代码。

### 3. 如何关闭 ASLR 调试？

`setarch $(uname -m) -R ./app`，或 gdb 的 `set disable-randomization on`，或 `personality(ADDR_NO_RANDOMIZE)`，或临时写 `/proc/sys/kernel/randomize_va_space`。

### 4. ASLR 能完全防止缓冲区溢出利用吗？

不能。它只让地址不可预测，信息泄漏、32 位暴力枚举、非 PIE 固定 gadget 都可能绕过。需要配合 NX、canary、RELRO、CFI 等。

## 十二、极简口诀

**ASLR 随基址，栈堆库全搬家；**

**非 PIE 代码固定，PIE 才能全随机；**

**randomize_va_space 零关二全开；**

**setarch -R 关随机，信息泄漏仍能绕。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
