# ELF 文件结构完整解析（可执行 / 静态库 / 动态库）

## 一、前言

ELF（Executable and Linkable Format）是 Linux 下目标文件、静态库、共享库、可执行文件、CoreDump 的统一格式：

- `.o`：可重定位目标文件（`ET_REL`）；
- `.a`：`ar` 归档，里面是一堆 `.o`；
- `.so`：共享对象（`ET_DYN`）；
- 可执行文件：`ET_EXEC`（非 PIE）或 `ET_DYN`（PIE）；
- core：`ET_CORE`。

核心总纲：**ELF 有两套视图：链接视图看 section（给链接器），执行视图看 segment（给内核/加载器）。** 看懂这两张表，就搞懂了 ELF。

## 二、ELF 头

`readelf -h app` 输出的关键字段：

| 字段 | 含义 |
|---|---|
| `Magic` | `7f 45 4c 46`，即 `\x7fELF` |
| `Class` | `ELF32` / `ELF64` |
| `Data` | 小端 / 大端 |
| `Type` | `REL` / `EXEC` / `DYN` / `CORE` |
| `Machine` | x86-64、ARM、AArch64 等 |
| `Entry point address` | 程序入口虚拟地址（`_start`） |
| `Start of program headers` | 程序头表偏移 |
| `Start of section headers` | 节头表偏移 |
| `Number of program headers` | segment 数量 |
| `Number of section headers` | section 数量 |

### e_type 的四种常见值

| 值 | 名称 | 对应文件 |
|---|---|---|
| 1 | `ET_REL` | `.o` 可重定位目标文件 |
| 2 | `ET_EXEC` | 非 PIE 可执行文件，地址固定 |
| 3 | `ET_DYN` | PIE 可执行文件 / 共享库 |
| 4 | `ET_CORE` | CoreDump |

`ET_EXEC` 和 `ET_DYN` 都可能可执行；区分 PIE 和共享库可以看是否有 `PT_INTERP`、`file` 输出，或 `readelf -h` 结合动态段判断。

## 三、section：链接视图

### 1. 常见 section

| section | 作用 |
|---|---|
| `.text` | 机器指令 |
| `.rodata` | 只读常量、字符串字面量 |
| `.data` | 已初始化全局/静态变量 |
| `.bss` | 未初始化/零初始化全局/静态变量（不占文件空间） |
| `.init` / `.fini` | 进程/共享库初始化、清理代码 |
| `.init_array` / `.fini_array` | 构造器/析构器函数指针数组 |
| `.plt` / `.got` / `.got.plt` | 动态调用跳板与地址表 |
| `.symtab` / `.strtab` | 完整符号表与字符串表 |
| `.dynsym` / `.dynstr` | 动态符号表与字符串表 |
| `.rela.text` / `.rela.dyn` | 重定位项 |
| `.eh_frame` / `.eh_frame_hdr` | 异常展开、栈回溯信息 |
| `.comment` | 编译器版本等注释 |
| `.debug_*` | DWARF 调试信息 |
| `.note.*` | build-id、ABI 标记等 |

### 2. 节头表字段

每个 `Elf64_Shdr` 包含：

- `sh_name`：节名在 `.shstrtab` 中的偏移；
- `sh_type`：`PROGBITS`、`SYMTAB`、`STRTAB`、`RELA`、`NOBITS` 等；
- `sh_flags`：`ALLOC`、`WRITE`、`EXECINSTR` 等；
- `sh_addr`：运行时虚拟地址（可加载节才有）；
- `sh_offset`：文件内偏移；
- `sh_size`：大小；
- `sh_link` / `sh_info`：关联的其他节/索引；
- `sh_addralign`：对齐；
- `sh_entsize`：表项大小。

`.bss` 的 `sh_type` 是 `NOBITS`，文件里没有内容，只有大小。

### 3. 静态库不是 ELF

`.a` 文件本身的格式是 `ar` 归档：

```text
!<arch>\n
成员头（60 字节）+ 成员数据
```

成员是 `.o`（ELF），另有一个特殊的符号索引成员（通常名为 `/`），记录"符号 → 成员"的映射，链接器靠它快速抽取。

```bash
ar t libfoo.a          # 成员列表
ar x libfoo.a          # 解包
nm -s libfoo.a         # 查看归档符号索引
```

## 四、segment：执行视图

### 1. 程序头表

内核和动态加载器只看程序头。常见 `p_type`：

| 类型 | 作用 |
|---|---|
| `PT_LOAD` | 需要映射到内存的段（代码/数据） |
| `PT_DYNAMIC` | 动态链接信息（`DT_NEEDED` 等） |
| `PT_INTERP` | 动态链接器路径（如 `ld-linux-x86-64.so.2`） |
| `PT_NOTE` | build-id、ABI 等注释 |
| `PT_PHDR` | 程序头表自身位置 |
| `PT_TLS` | 线程局部存储模板 |
| `PT_GNU_STACK` | 栈是否可执行 |
| `PT_GNU_RELRO` | RELRO 只读区域 |
| `PT_GNU_PROPERTY` | 安全特性（如 CET） |

每个 `PT_LOAD` 有：

- `p_offset` / `p_filesz`：文件中的位置和大小；
- `p_vaddr` / `p_memsz`：内存中的地址和大小；
- `p_flags`：读/写/执行权限；
- `p_align`：对齐。

关键关系：`p_memsz >= p_filesz`。多出来的部分就是 `.bss`，加载时补零，不从文件读。

### 2. section 与 segment 的关系

- 一个 segment 可以包含多个 section；
- 只有带 `ALLOC` 标志的 section 才会进入 `PT_LOAD`；
- 调试节、符号表不进内存，只在文件里。

```bash
readelf -S app        # section 视图
readelf -l app        # segment 视图
objdump -h app        # section 概览
```

## 五、动态库的特殊结构

`.so` 除普通段外，还有：

- `PT_DYNAMIC` → `.dynamic` 段，包含 `DT_NEEDED`、`DT_SONAME`、`DT_RPATH`、`DT_RUNPATH`、`DT_INIT_ARRAY` 等；
- `.dynsym` / `.dynstr`：运行时符号；
- `.gnu.version*`：符号版本；
- `.gnu.hash` / `.hash`：符号哈希表，加速查找。

```bash
readelf -d libfoo.so | grep -E 'SONAME|NEEDED|RPATH|RUNPATH'
readelf -V libfoo.so
```

## 六、CoreDump 的结构

Core 文件是 `ET_CORE`：

- `PT_NOTE`：保存寄存器、进程状态、信号信息（`NT_PRSTATUS`、`NT_PRPSINFO`、`NT_FILE`）；
- `PT_LOAD`：保存出问题时的内存映射。

gdb 读取 core 时，先读 note 恢复寄存器和信号，再映射内存段，然后还原调用栈。

```bash
file core
readelf -n core | head -40
gdb ./app core
```

## 七、常用命令速查

| 目的 | 命令 |
|---|---|
| 判断文件类型 | `file app libfoo.so libfoo.a` |
| ELF 头 | `readelf -h app` |
| 程序头 | `readelf -l app` |
| 节头 | `readelf -S app` |
| 动态段 | `readelf -d libfoo.so` |
| 符号表 | `readelf -s app` |
| 重定位 | `readelf -r app` |
| 反汇编 | `objdump -d app` |
| 段大小统计 | `size app` |
| 静态库成员 | `ar t libfoo.a` |

## 八、常见报错与 ELF 的关系

| 报错 | ELF 层面的原因 |
|---|---|
| `Exec format error` | `e_machine`/Class/字节序不匹配，或缺少解释器 |
| `wrong ELF class: ELFCLASS32` | 32/64 位不匹配 |
| `cannot open shared object file` | `PT_INTERP`/`DT_NEEDED` 指向的库找不到 |
| `no symbols`（nm） | `.symtab` 被 strip，只剩 `.dynsym` |
| `not a dynamic executable` | 静态链接，无 `PT_INTERP` |
| `text relocations` | 共享库未用 PIC 编译，代码段含重定位 |

## 九、面试标准简答

### 1. section 和 segment 的区别？

section 是链接视图，给链接器和调试工具看，按内容类型划分（`.text`、`.data` 等）；segment 是执行视图，给内核和加载器看，按内存权限和加载方式划分（`PT_LOAD` 等）。一个 segment 可包含多个 section。

### 2. ET_EXEC 和 ET_DYN 的区别？

`ET_EXEC` 是非 PIE 可执行文件，代码地址在链接时固定；`ET_DYN` 是位置无关的可执行文件（PIE）或共享库，加载地址由内核/加载器决定，支持 ASLR。PIE 可执行文件也有 `PT_INTERP`，共享库通常没有。

### 3. .bss 为什么不占文件空间？

`.bss` 存放未初始化/零初始化数据，内容全是 0。ELF 用 `SHT_NOBITS` 表示它，`p_filesz` 不包含它，`p_memsz` 包含；加载时内核直接映射零页，不需要在文件里存一堆 0。

### 4. 静态库和共享库在 ELF 层面有什么区别？

静态库是 `ar` 归档，成员是 `ET_REL` 的 `.o`，链接时按需抽取并复制进产物；共享库是单个 `ET_DYN` 的 ELF，链接时只记录依赖，运行时由动态链接器映射和重定位。

## 十、极简口诀

**ELF 两视图：section 链接，segment 运行；**

**REL 是 .o，EXEC/DYN 可执行，CORE 是崩溃快照；**

**bss 是 NOBITS，filesz 小 memsz 大；**

**readelf 看全貌，ar 拆静态库。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
