# 程序启动入口 _start 与 main 关系

## 一、前言

`main` 不是程序的第一条指令。内核根本不认识 `main`，它只认 ELF 头里的入口地址 `e_entry`，那里是 `_start`。

核心总纲：**内核 → `_start`（crt 启动代码）→ `__libc_start_main` → 构造器 → `main` → `exit`。** `main` 只是被启动代码调用的一次普通函数。

## 二、内核如何启动程序

以 Linux x86-64 为例：

1. `execve("./app", argv, envp)`；
2. 内核读取 ELF 头，校验格式、架构；
3. 按程序头映射 `PT_LOAD` 段；
4. 找到 `PT_INTERP`，映射动态链接器（动态链接时）；
5. 在用户栈上布置启动信息：

```text
argc
argv[0] ... argv[argc-1] NULL
envp[0] ... NULL
auxv 键值对 ... AT_NULL
```

6. 跳转到 `e_entry`，也就是 `_start`。

```bash
readelf -h app | grep Entry
objdump -d app | grep -A20 '<_start>'
```

## 三、_start 做了什么

`_start` 来自 C 运行库的启动文件（`crt1.o`、PIE 用 `Scrt1.o`），不是编译器为每个程序生成的。

x86-64 glibc 的 `_start` 大致逻辑（汇编）：

```asm
_start:
    xor  %ebp, %ebp          # 清空帧指针，标记最外层
    mov  %rdx, %r9           # rtld_fini：动态链接器的清理函数
    pop  %rsi                # argc
    mov  %rsp, %rdx          # argv
    and  $~15, %rsp          # 16 字节对齐
    push %rax
    push %rsp                # stack_end
    xor  %r8d, %r8d          # fini
    xor  %ecx, %ecx          # init（现代版本由 libc 内部处理）
    lea  main(%rip), %rdi    # main 的地址
    call *__libc_start_main@GOTPCREL(%rip)
    hlt                      # main 正常返回后不会到这里
```

要点：

- `main` 的地址作为第一个参数传给 `__libc_start_main`；
- `argc`、`argv`、`envp` 来自内核布置的栈；
- `_start` 自己不调用 `main`，而是交给 libc。

## 四、__libc_start_main 做了什么

`__libc_start_main` 是 libc 的启动核心，主要工作：

1. **安全初始化**：设置栈保护 canary、指针保护（pointer guard）；启用 `FORTIFY_SOURCE` 相关检查；
2. **TLS 初始化**：设置线程局部存储；
3. **保存环境**：`__environ`、程序名等；
4. **运行构造器**：执行 `.init`、`.init_array` 中的函数（C++ 全局对象构造、`__attribute__((constructor))`）；
5. **调用 main**：`exit(main(argc, argv, envp))`；
6. **注册清理**：`atexit`、`__cxa_atexit` 注册的函数在 `exit` 时执行。

现代 glibc 内部会调用 `__libc_start_call_main`，再进入 `main`。`main` 返回后，返回值被传给 `exit`。

## 五、main 的参数从哪来

```c
int main(int argc, char* argv[], char* envp[]);
```

- `argc`：参数个数；
- `argv`：参数字符串指针数组，`argv[argc] == NULL`；
- `envp`：环境变量数组，`envp[i] == NULL` 结束。

它们都不是 `main` 自己解析的，而是内核放在栈上，`_start` 读出，再经 `__libc_start_main` 传给 `main`。

标准 C 只保证 `main` 的前两个参数；`envp` 是扩展，可移植性差。可移植写法：

```c
extern char** environ;
```

## 六、构造器与 init_array

### 1. C++ 全局对象

```cpp
struct Logger {
    Logger() { /* 在 main 前执行 */ }
    ~Logger() { /* 在 exit 时执行 */ }
};
Logger g_logger;
```

编译器把它放进 `.init_array`，由 `__libc_start_main` 在 `main` 前调用。

### 2. GCC 扩展

```c
__attribute__((constructor))
static void before_main(void) {
    // main 之前执行
}

__attribute__((destructor))
static void after_main(void) {
    // exit 时执行
}
```

### 3. 顺序

- 依赖库先于使用者初始化；
- 同一编译单元内大致按定义顺序；
- 不同编译单元之间顺序未定义；
- 析构在 `exit` 时逆序执行（`__cxa_atexit`）。

## 七、main 返回之后

```c
int main(void) {
    return 0;
}
```

等价于调用 `exit(0)`：

1. 执行 `atexit` / `__cxa_atexit` 注册的函数（逆序）；
2. 刷新并关闭 stdio 流；
3. 执行 `_exit` 系统调用，内核回收资源。

如果调用 `_exit` 或 `_Exit`，会跳过清理；`abort` 直接 `SIGABRT`，也不走正常清理。

## 八、自定义入口

可以替换入口，但要知道自己在做什么：

```bash
gcc main.c -nostartfiles -Wl,-e,my_entry -o app
```

```c
void my_entry(void) {
    // 此时 libc 尚未初始化，不能用 printf/malloc 等
    // 需要自己调用 exit 或 _exit
}
```

常见用途：Bootloader、内核、极简运行时、调试。普通应用不要替换 `_start`。

## 九、常见问题

### 1. undefined reference to `main`

链接器找不到 `main`。检查是否忘记定义、函数签名拼写错误、文件没参与链接、或者用了 `-nostartfiles` 却没提供入口。

### 2. undefined reference to `_start`

启动文件没链接进来。检查是否误用 `-nostartfiles`、是否手工调用 `ld` 而没带 `crt1.o`。

### 3. main 之前就崩溃

通常是全局对象构造器或 `__attribute__((constructor))` 里的代码问题。用 gdb 在 `_start` 下断点，单步定位。

### 4. 构造器顺序问题

不同编译单元的全局对象构造顺序未定义。用函数内 static（Meyers Singleton）或显式初始化函数规避。

### 5. main 返回值被忽略

`main` 的返回值是进程退出码，shell 通过 `$?` 获取。返回非 0 表示失败；`return` 与 `exit` 都会走清理流程。

## 十、调试与查看

| 目的 | 命令 |
|---|---|
| 查看入口地址 | `readelf -h app | grep Entry` |
| 反汇编 _start | `objdump -d app | grep -A20 '<_start>'` |
| 查看 main 地址 | `nm app | grep ' main$'` |
| gdb 断在入口 | `gdb ./app` → `break _start` |
| 查看构造器 | `readelf -x .init_array app` |
| 查看动态段 init | `readelf -d app | grep INIT` |

## 十一、面试标准简答

### 1. main 是程序入口吗？

不是。内核跳转的是 ELF 头记录的 `_start`，由 C 运行库提供。`_start` 从内核布置的栈中取出参数，调用 `__libc_start_main`，后者完成初始化、运行构造器，最后才调用 `main`。

### 2. argc 和 argv 是怎么传到 main 的？

内核在 `execve` 时把它们放到用户栈顶；`_start` 用 `pop` 和 `mov` 取出 `argc`、`argv`，作为参数传给 `__libc_start_main`，再由它传给 `main`。

### 3. main 返回后发生了什么？

返回值被传给 `exit`：执行 `atexit`/C++ 析构、刷新 stdio、调用 `_exit` 系统调用。内核回收地址空间、关闭文件描述符、唤醒父进程。

### 4. 全局对象的构造函数什么时候执行？

在 `main` 之前，由 `__libc_start_main` 调用 `.init_array` 中的函数执行。不同编译单元的顺序未定义；析构在 `exit` 时逆序执行。

## 十二、极简口诀

**内核跳 _start，不看 main 名；**

**_start 取 argc/argv，交给 __libc_start_main；**

**构造器先跑完，最后才进 main；**

**main 返回走 exit，_exit 跳过清理。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
