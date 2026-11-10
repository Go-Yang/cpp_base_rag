# addr2line 行号定位崩溃代码

## 一、前言

拿到一个运行时地址（崩溃地址、backtrace 里的返回地址、性能采样地址），怎么知道它对应哪行源码？`addr2line` 就是做这件事的。

核心总纲：**addr2line 把"地址"翻译成"文件:行号 + 函数名"，前提是二进制里有 DWARF 调试信息，且地址是相对该二进制的正确偏移。**

## 二、基本用法

```bash
addr2line -e app -f -C -i 0x401234
```

参数：

| 参数 | 作用 |
|---|---|
| `-e app` | 指定可执行文件/共享库 |
| `-f` | 显示函数名 |
| `-C` | demangle C++ 名字 |
| `-i` | 展开内联函数调用链 |
| `-p` | 一行一个结果，便于阅读 |
| `-a` | 显示地址 |
| `-s` | 只显示 basename |

输出示例：

```text
main
/home/user/app.c:42
```

如果地址无效或没有调试信息：

```text
??
??:0
```

## 三、必须注意的地址问题

### 1. 绝对地址 vs 偏移

`addr2line` 需要的是**相对该 ELF 的地址**（`st_value` 口径）。

- 非 PIE 可执行文件：运行时地址通常就是链接地址，可直接用；
- PIE / 共享库：运行时地址 = 加载基址 + 偏移，必须先减去基址。

获取基址：

```gdb
(gdb) info proc mappings
(gdb) info files
```

或运行中：

```bash
cat /proc/<pid>/maps
```

例如 `libfoo.so` 映射在 `0x7ffff7a00000`，崩溃地址 `0x7ffff7a01234`，则传给 addr2line 的偏移是 `0x1234`。

### 2. 返回地址减一

backtrace 里的返回地址指向**调用指令的下一条**。要定位调用点，很多工具会减一：

```bash
addr2line -e app -f -C 0x$(printf '%x' $((0x401234 - 1)))
```

GDB 的 `bt` 已经处理了这一点，手动从栈里取地址时要注意。

### 3. ASLR

ASLR 开启时运行时地址每次都变。用 `setarch -R` 关闭，或按基址换算偏移。

## 四、批量处理

### 1. 从 backtrace 提取地址

```bash
gdb -batch -ex 'bt' ./app core | grep -oE '0x[0-9a-f]+' | \
  xargs -I{} addr2line -e app -f -C -i {}
```

### 2. 从文件读取

```bash
addr2line -e app -f -C -i $(cat addresses.txt)
```

### 3. 一行输出

```bash
addr2line -e app -f -C -i -p 0x401234 0x401250
```

## 五、调试信息从哪来

### 1. 编译选项

```bash
gcc -g -Og app.c -o app
```

- `-g` 生成 DWARF；
- `-Og` 优化但不破坏调试体验；
- `-O2 -g` 也可用，但部分变量会被优化掉，行号可能跳变。

### 2. 分离调试文件

```bash
objcopy --only-keep-debug app app.debug
objcopy --strip-debug app
objcopy --add-gnu-debuglink=app.debug app
```

发布二进制被 strip 后：

```bash
addr2line -e app.debug -f -C -i 0x401234
```

### 3. build-id 查找

```bash
readelf -n app | grep 'Build ID'
# 在 /usr/lib/debug/.build-id/xx/yyyy.debug 查找
```

`debuginfod` 可以按 build-id 自动获取：

```bash
export DEBUGINFOD_URLS="https://debuginfod.elfutils.org/"
eu-addr2line -e app 0x401234
```

## 六、替代工具

| 工具 | 特点 |
|---|---|
| `addr2line` | binutils 自带，简单 |
| `eu-addr2line` | elfutils，支持 debuginfod |
| `llvm-symbolizer` | LLVM 工具链，内联展开好 |
| `gdb info line *addr` | 交互式 |
| `objdump -dl` | 反汇编带源码行 |

`llvm-symbolizer` 用法：

```bash
llvm-symbolizer --obj=app 0x401234
```

## 七、常见问题

### 1. 输出 ?? ???

- 地址不对（PIE 未减基址、返回地址未减一）；
- 二进制没有调试信息；
- 二进制与崩溃版本不匹配；
- 共享库选错了文件。

### 2. 行号不准

- 优化导致指令重排、内联；
- 多个源码版本；
- `-g` 与二进制不同步。

用 `-Og` 或 `-O0` 复现，或结合反汇编判断。

### 3. 内联函数只显示外层

加 `-i` 展开内联调用链；`llvm-symbolizer` 对内联支持更好。

### 4. 发布环境没有调试信息

保留带符号的二进制/`.debug` 文件，按 build-id 对应；或者部署 debuginfod 服务。

## 八、实战流程

1. 从 core/gdb/采样拿到地址；
2. 判断是 PIE/共享库，换算偏移；
3. `addr2line -e <对应ELF> -f -C -i <偏移>`；
4. 打开源码，结合反汇编和变量确认；
5. 若行号异常，换 `-Og` 版本或检查版本匹配。

## 九、面试标准简答

### 1. addr2line 是做什么的？

把 ELF 中的地址翻译成源码文件、行号和函数名。它依赖 DWARF 调试信息，需要正确的相对地址。

### 2. 为什么 addr2line 输出 ???

常见原因：地址是运行时绝对地址但没减加载基址、二进制没有 `-g` 调试信息、二进制与运行版本不匹配、地址是返回地址但没减一。

### 3. PIE 程序怎么用 addr2line？

先获取加载基址（`/proc/pid/maps`、gdb `info proc mappings`），用运行时地址减去基址得到偏移，再把偏移传给 addr2line。

### 4. 生产环境没有调试符号怎么办？

保留带符号的二进制或分离的 `.debug` 文件，按 build-id 管理；用 `debuginfod` 自动查找；或在构建时生成并归档符号包。

## 十、极简口诀

**地址翻源码，addr2line 来干；**

**-e 指定 ELF，-f 函数 -C 反修饰；**

**PIE 先减基址，返回地址减一；**

**没有调试信息，?? 找 build-id。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
