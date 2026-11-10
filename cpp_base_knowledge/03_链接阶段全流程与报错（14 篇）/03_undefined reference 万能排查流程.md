# undefined reference 万能排查流程

## 一、前言

`undefined reference to 'xxx'`（MSVC 对应 `LNK2019 unresolved external symbol`）是**链接器报错**，不是编译器报错。它的含义只有一个：

> 链接器遍历了所有输入的目标文件、静态库、动态库，仍然找不到符号 `xxx` 的定义。

核心总纲：**编译器只负责判断"声明是否合法"，链接器才负责找"定义到底在哪"。** 出现这个报错时，源码语法一定是通的，排查方向不是改语法，而是查符号表。

## 二、底层原理

### 1. 编译单元与符号表

每个 `.c` / `.cpp` 单独编译成一个 `.o`，`.o` 里有两类符号：

- **已定义符号**：`T`（代码段）、`D`（已初始化数据）、`B`（未初始化数据）、`R`（只读数据）
- **未定义符号**：`U`，表示"我在别处引用，但本单元没有定义"

C++ 符号经过 **name mangling**（如 `void foo(int)` → `_Z3fooi`），链接器按 mangled 名精确匹配。`nm -C`、`c++filt` 可以把名字还原成可读形式。C 语言不做 mangling，函数名就是符号名。

### 2. 链接器的工作

1. 合并所有输入目标文件的同名 section；
2. 用已定义符号解析所有 `U` 符号；
3. 为符号分配地址并完成重定位；
4. 仍然无法解析的 `U` 符号 → 报 `undefined reference`。

### 3. 与编译错误的区别

- 编译错误：语法、类型、声明问题，发生在 `.o` 生成之前；
- 链接错误：符号表问题，`.o` 已经成功生成。

所以不要拿查语法报错的思路查它——先看符号名和链接命令，而不是盯着报错行的源码。

## 三、根因分类（按排查优先级）

### 1. 根本没写定义

- 声明了函数/变量，但没有实现；
- 实现文件漏加进构建（Makefile / CMakeLists 漏了源文件）；
- 实现被 `#if 0` 或错误的条件编译分支裁掉。

### 2. 定义存在，但没参与链接

- 实现所在的 `.o` 没被链接；
- 实现放在静态库/动态库里，但没加 `-l`；
- 库路径没加 `-L`，或库名写错（`-lfoo` 对应 `libfoo.a` / `libfoo.so`）。

### 3. 静态库链接顺序错误（高频）

链接器按命令行**从左到右单遍扫描**：遇到库时只解析"当前尚未定义"的符号，扫过之后不再回头。规则是：

> **依赖方在前，被依赖方在后。**

```bash
# main.o 调用 foo，foo 内部调用 bar
gcc main.o -lfoo -lbar    # 正确：扫到 foo 时 bar 还未需要，扫到 bar 时能解析 foo 引入的未定义符号

gcc main.o -lbar -lfoo    # 错误：bar 先被扫过，之后 foo 才引入对 bar 的引用，没人再解析
# 典型报错：undefined reference to `bar'

# 两个库互相依赖时，用 group 强制多次扫描
gcc main.o -Wl,--start-group -lfoo -lbar -Wl,--end-group
```

### 4. 声明与定义不一致（符号名不同）

- 参数带 `const` / 引用 / 命名空间 / 类作用域不一致 → mangled 名不同；
- C++ 调用 C 函数没有 `extern "C"` → C++ 按 mangled 名去找，C 库只导出裸名；
- 头文件声明与源文件定义的函数签名不完全一致。

### 5. 符号可见性被限制

- 动态库用 `-fvisibility=hidden` 编译，导出符号却没加
  `__attribute__((visibility("default")))`；
- 链接脚本 / version script 限制了导出符号；
- `--exclude-libs` 等选项把符号隐藏；
- 静态库成员未被抽取：需要确认符号确实在库里。

### 6. 内联函数与模板（ODR 问题）

- `inline` 函数只在头文件声明、只在某一个 `.cpp` 定义 → 其他编译单元既没展开也没定义；
- 模板定义放在 `.cpp` → 其他编译单元实例化时看不到定义；
- 类模板成员函数定义在 `.cpp`，但没有显式实例化。

C++ 标准要求：inline 函数和模板的定义必须对每一个使用它的编译单元可见，所以它们通常要放在头文件里。

### 7. 特殊库与编译选项

| 报错符号                         | 缺失的链接项                    |
| -------------------------------- | ------------------------------- |
| `pthread_create`               | `-pthread`（编译和链接都加）  |
| `dlopen` / `dlsym`           | `-ldl`（glibc 2.34 之前需要） |
| `sin` / `cos` / `sqrt`     | `-lm`                         |
| `std::cout` / `operator new` | 用 `g++` 链接，而不是 `gcc` |

### 8. 架构 / ABI 不匹配

32 位目标文件与 64 位库混链、不同 C++ ABI（`_GLIBCXX_USE_CXX11_ABI`）、不同编译器版本生成的库，都会表现为"符号找不到"或运行期符号解析失败。用 `file`、`readelf -h` 检查目标文件和库的架构。

## 四、标准排查流程（命令化）

### Step 0：看清完整报错

记录三样东西：**哪个目标文件、哪个符号、真实链接命令**。

```bash
make V=1                      # Makefile 项目：打印完整编译/链接命令
gcc -### main.c foo.c -o app   # 只看命令不执行，确认每个 .o 和库都参与了链接
```

### Step 1：确认符号是否被定义

```bash
nm -C a.o | grep 'xxx$'            # U 表示未定义；T/D/B/R 表示已定义
nm -C libfoo.a | grep xxx          # 在静态库里找
readelf -Ws libfoo.so | grep xxx   # 在动态库里找
```

### Step 2：确认库路径与库名

```bash
ldconfig -p | grep foo             # 系统里是否有这个库
gcc main.o -L/path/to/lib -lfoo -o app
```

### Step 3：检查静态库链接顺序

依赖方在前，被依赖方在后；互相依赖时用 `--start-group` / `--end-group`。

### Step 4：检查 C/C++ 混编

```bash
nm -C libcfoo.a | grep foo         # 看导出的是裸名还是 C++ mangled 名
```

C 接口头文件统一加：

```c
#ifdef __cplusplus
extern "C" {
#endif

void cfoo(void);

#ifdef __cplusplus
}
#endif
```

### Step 5：检查符号可见性

```bash
objdump -T libfoo.so | grep xxx    # 动态符号表里是否真的导出
readelf --dyn-syms libfoo.so | grep xxx
```

### Step 6：运行时动态链接排查

```bash
ldd -r ./app                                  # 直接报出未解析的动态符号
LD_DEBUG=libs,symbols ./app 2>&1 | grep xxx   # 跟踪动态库加载与符号查找
```

## 五、典型案例

### 案例 1：C++ 调用 C 库缺少 extern "C"

```cpp
// 错误：C++ 按 _Z4foov 查找，C 库只导出 foo
extern void foo();     // 实际符号名是 _Z4foov

// 正确：告诉编译器按 C 规则生成/查找符号
extern "C" void foo(); // 实际符号名是 foo
```

### 案例 2：模板定义放在 .cpp

```cpp
// stack.h
template <typename T>
class Stack {
public:
    void push(const T& value);
};

// stack.cpp —— 其他编译单元看不到这个定义
template <typename T>
void Stack<T>::push(const T& value) { /* ... */ }

// main.cpp
Stack<int> s;
s.push(1);   // undefined reference to `Stack<int>::push(int const&)'
```

修复：定义放头文件；或在 `stack.cpp` 里显式实例化 `template class Stack<int>;`。

### 案例 3：inline 函数定义不可见

```cpp
// foo.h
inline void foo();

// foo.cpp
void foo() {}   // 定义只存在于这个编译单元

// main.cpp
foo();          // inline 函数没有可展开的定义 → undefined reference
```

修复：inline 函数定义必须放在头文件。

### 案例 4：静态库顺序错误

```bash
# libfoo.a 依赖 libbar.a
gcc main.o -lbar -lfoo -o app   # 错误
gcc main.o -lfoo -lbar -o app   # 正确
```

### 案例 5：链接了错误的库版本

系统里同时存在多个版本的 `libfoo.so`，`ldconfig -p` 显示的不一定是 `-L` 指定的那个。用 `ldd ./app | grep foo` 确认最终加载的是哪一个。

## 六、命令速查表

| 目的                 | 命令                                              |
| -------------------- | ------------------------------------------------- |
| 查看目标文件全部符号 | `nm -C a.o`                                     |
| 只看未定义符号       | `nm -u -C a.o`                                  |
| 查看静态库成员       | `ar t libfoo.a`                                 |
| 查看动态库导出符号   | `objdump -T libfoo.so` / `readelf --dyn-syms` |
| 查找符号在哪个库     | `for f in *.a; do nm -C --defined-only "$f"       |
| 查看真实链接命令     | `make V=1` / `gcc -###`                       |
| 检查运行时未解析符号 | `ldd -r ./app`                                  |
| 跟踪动态链接过程     | `LD_DEBUG=libs,symbols ./app`                   |
| 检查架构/位数        | `file a.o libfoo.so app`                        |

## 七、预防规范

1. 头文件只放声明，定义放源文件；inline 函数和模板是例外，定义放头文件。
2. C 接口统一用 `extern "C"` 包裹，头文件加 `__cplusplus` 条件编译。
3. 静态库链接顺序：使用者在前、被使用者在后；CMake 用 `target_link_libraries` 管理传递依赖。
4. 共享库显式控制导出符号：`-fvisibility=hidden` + `visibility("default")`，或 version script。
5. 构建共享库时加 `-Wl,--no-undefined`，把"运行时才炸"的问题提前到链接期。
6. 链接 C++ 目标文件一律用 `g++`，不要用 `gcc`。

## 八、面试标准简答

### 1. undefined reference 是编译期还是链接期？

链接期。编译阶段每个源文件独立生成 `.o`，只要声明合法就能通过；链接阶段才需要把 `U` 符号与其他目标文件/库中的定义对上。对不上就报 undefined reference。

### 2. 为什么静态库有链接顺序要求？

链接器对静态库是单遍扫描，处理某个库时只解析当前尚未定义的符号，之后不再回头。所以依赖别人的库必须放在命令行更靠后的位置，否则它引用到的符号还没被引入，就没人解析。

### 3. 为什么模板要定义在头文件？

模板本身不是代码，实例化发生在使用处。编译器在实例化 `Stack<int>` 时必须看到成员函数的定义，否则只能生成一个未定义引用，链接期就会报错（或在 C++ 中触发 ODR 相关问题）。

### 4. undefined reference 和 multiple definition 的区别？

- `undefined reference`：找不到定义 —— 该有的东西没来；
- `multiple definition`：同一个符号被定义了多次 —— 不该重复的东西来了多份。

一个在"缺"，一个在"多"，排查方向相反。

## 九、极简口诀

**未定义找链接，先查符号再看库；**

**声明定义要一致，C++ 混编 extern "C"；**

**静态库依赖在前，模板内联放头文件；**

**nm 查表 ldd -r，真实命令 -### 看。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
