# multiple definition 多重定义根治方案

## 一、前言

`multiple definition of 'xxx'`（MSVC 对应 `LNK2005`）是链接期报错，含义是：

> 同一个强符号在多个目标文件/库中被定义，链接器不知道该用哪一个。

它和 `undefined reference` 正好相反：一个是"缺"，一个是"多"。核心总纲：**头文件放声明，源文件放定义；一个强符号全局只能有一份定义。**

## 二、底层原因

### 1. 强符号与弱符号

- 普通全局函数、全局变量是**强符号**（`GLOBAL`）；
- `__attribute__((weak))`、模板隐式实例化等产生**弱符号**（`WEAK`）；
- 多个强定义 → 报错；强 + 弱 → 选强；多个弱 → 任选一个，不报错。

`multiple definition` 只针对强符号。

### 2. 编译单元与 ODR

C++ 的 ODR（One Definition Rule）要求：一个实体在整个程序中只能有一份定义（inline 函数、模板、类定义允许每个编译单元各有一份**完全相同**的定义，链接器再合并）。

违反 ODR 的常见形式：头文件里写普通函数/变量定义，被多个 `.cpp` 包含，每个编译单元都生成一份强定义。

### 3. C 的 tentative definition 与 -fno-common

C 语言里，文件作用域的 `int x;` 是**暂定定义**（tentative definition），传统上生成 `COMMON` 符号，链接器会把多个 `COMMON` 合并成一份。

GCC 10 起默认 `-fno-common`，`int x;` 直接变成强定义。于是老代码里"头文件写 `int x;`、多个源文件包含"的写法，在新编译器上会突然报 `multiple definition`。

## 三、高频场景与根治方案

### 1. 头文件定义全局变量（最经典）

```c
// config.h —— 错误写法
int g_count = 0;          // 每个包含它的 .cpp 都定义一份

// 正确写法
extern int g_count;       // 头文件只声明

// config.cpp
int g_count = 0;          // 唯一一份定义
```

C++17 起可以用内联变量：

```cpp
// config.h
inline int g_count = 0;   // 允许在多个编译单元定义，链接器合并
```

### 2. 头文件定义普通函数

```c
// util.h —— 错误写法
void log_msg(const char* msg) { /* ... */ }   // 多个 TU 各自定义

// 正确写法一：头文件声明，.cpp 定义
void log_msg(const char* msg);

// 正确写法二：确实要放头文件就加 inline
inline void log_msg(const char* msg) { /* ... */ }
```

### 3. 多个源文件重复实现同名函数

拷贝代码、合并分支、重复引入第三方源码时，两个 `.cpp` 都定义了 `init()`。修复：删掉重复实现，或把其中一个改为 `static` / 匿名命名空间（内部链接，不参与全局符号解析）。

```cpp
namespace {
void init() { /* 只在本编译单元可见 */ }
}
```

### 4. 静态库与目标文件重复链接

```bash
gcc main.o foo.o -lfoo -o app
```

如果 `libfoo.a` 里也有 `foo.o`，且链接器因其他符号抽取了它，`foo.o` 中的强符号就会和命令行上的 `foo.o` 冲突。修复：不要同时链接同一份代码的 `.o` 和包含它的 `.a`。

### 5. 两个第三方库导出同名符号

例如两个库都定义了 `log`、`init`、`version` 这类通用名。表现可能是 `multiple definition`（静态库）或运行期符号被覆盖（动态库）。修复：

- 优先升级/更换库，选择带命名空间的版本；
- C 接口加统一前缀（`foo_init`、`bar_init`）；
- 用 `objcopy --prefix-symbols` 重命名（激进，慎用）；
- 动态库场景用符号可见性/版本脚本隔离。

### 6. 内联函数/模板缺少 inline

- 头文件里定义了普通函数但没加 `inline` → 多个 TU 强定义；
- 类内定义的成员函数隐式 inline，没问题；类外定义在头文件里必须显式 `inline`；
- 模板函数/类模板允许每个 TU 实例化，链接器合并弱符号，通常不报 multiple definition。

### 7. LTO 与 -fcommon 的差异

开启 LTO 后，某些跨编译单元的重复定义会被优化器合并或报更严格的诊断；老项目迁移到 GCC 10+ 时，优先排查 `-fcommon` 依赖。

## 四、排查流程

### Step 1：拿到完整报错

```text
multiple definition of `g_count'
main.o:(.bss+0x0): first defined here
foo.o:(.bss+0x0): first defined here
ld returned 1 exit status
```

报错会给出两份定义所在的目标文件，这是最关键的线索。

### Step 2：确认符号来自哪里

```bash
nm -C --defined-only *.o | grep g_count
nm -C --defined-only libfoo.a | grep g_count
```

### Step 3：确认头文件是否被多处包含

```bash
grep -rn "int g_count" include/ src/
g++ -E main.cpp | grep -n "g_count"   # 看预处理展开后的真实定义
```

### Step 4：用 map 文件看链接器抽取了哪些成员

```bash
gcc main.o -lfoo -Wl,-Map=link.map -o app
grep -n "g_count" link.map
```

### Step 5：临时验证（不作为修复）

```bash
-Wl,--allow-multiple-definition   # 允许重复定义，链接器选第一个
```

这个选项会掩盖问题，只适合临时定位，不要放进正式构建。

## 五、修复方案速查

| 场景 | 修复 |
|---|---|
| 头文件全局变量 | `extern` 声明 + 一个 `.cpp` 定义；或 C++17 `inline` 变量 |
| 头文件普通函数 | 声明放头文件、定义放 `.cpp`；或加 `inline` |
| 重复实现 | 删除重复；内部使用的加 `static` / 匿名命名空间 |
| `.o` 与 `.a` 重复 | 只保留一种链接方式 |
| 第三方库同名符号 | 前缀/命名空间/换库/可见性隔离 |
| 老代码依赖 common | 临时 `-fcommon`，长期改为 `extern` 方案 |
| 模板/内联 | 确认定义可见且带 `inline`，不要重复定义非 inline 版本 |

## 六、预防规范

1. **头文件只放声明**：函数声明、`extern` 变量、类定义、模板定义、`inline` 函数。
2. **定义只放一处**：全局变量/普通函数在 `.cpp` 中唯一定义。
3. **内部实现加内部链接**：`static` 或匿名命名空间，避免污染全局符号表。
4. **C 接口加前缀**，避免 `init`、`log`、`open` 这类通用名。
5. **新项目不要依赖 `-fcommon`**；迁移老项目时显式加 `extern`。
6. **构建时打开 `-Wl,--warn-common`**，提前发现公共符号合并问题。
7. **不要用 `--allow-multiple-definition` 作为正式修复**。

## 七、面试标准简答

### 1. multiple definition 和 undefined reference 的区别？

`multiple definition` 是同一个强符号被定义了多份，链接器无法选择；`undefined reference` 是符号只有引用没有定义。前者是"多"，后者是"缺"，排查方向相反。

### 2. 为什么头文件里定义变量会导致 multiple definition？

头文件内容在预处理阶段被文本复制进每个包含它的编译单元，每个 `.cpp` 都会生成一份该变量的定义。链接时多个强定义相遇就报错。正确做法是头文件写 `extern`，在一个 `.cpp` 中定义。

### 3. C 语言的 tentative definition 和 -fno-common 是什么关系？

C 中文件作用域的 `int x;` 是暂定定义，传统 GCC 把它放进 `COMMON` 段，链接器会合并多个 COMMON 符号。GCC 10 默认 `-fno-common` 后，它变成普通强定义，老代码就会报 multiple definition。修复是改为 `extern` 声明 + 单一定义。

### 4. 模板和 inline 函数为什么允许多份定义？

它们属于 ODR 的例外：标准允许每个使用它们的编译单元各有一份完全相同的定义，链接器把这些弱符号（COMDAT）合并成一份。前提是所有定义必须一致，否则行为未定义。

## 八、极简口诀

**多重定义是"多"，强符号只能有一份；**

**头文件只放声明，定义收进源文件；**

**C++17 inline 变量，C 老代码加 extern；**

**内部实现匿名命名，第三方冲突加前缀。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
