# extern跨文件符号引用规范

## 一、前言

`extern` 用来声明"这个符号在别处定义"。它本身不分配内存、不产生定义，只告诉编译器类型和名字，具体地址留给链接器。

核心总纲：**头文件放声明（extern），源文件放唯一定义；一个强符号全局只能有一份定义。** 混用声明/定义是 multiple definition 和 undefined reference 的主要来源。

## 二、声明与定义

### 1. 定义

定义会分配存储（变量）或生成函数体（函数），并在目标文件中产生符号：

```c
int g_count = 0;       // 定义，.data
int g_zero;            // 定义（暂定定义），.bss
void foo(void) { }     // 定义，.text
```

### 2. 声明

声明只引入名字和类型，不分配存储：

```c
extern int g_count;    // 声明，引用别处的定义
void foo(void);        // 函数声明（函数默认外部链接）
```

### 3. 头文件标准写法

```c
// config.h
#ifndef CONFIG_H
#define CONFIG_H

extern int g_count;    // 声明
void config_init(void);

#endif
```

```c
// config.c
#include "config.h"

int g_count = 0;       // 唯一定义
void config_init(void) { g_count = 1; }
```

任何包含 `config.h` 的编译单元都只看到声明，不会产生重复定义。

## 三、链接属性

### 1. 外部链接

普通全局变量、普通函数默认是外部链接，可以被其他编译单元引用。

### 2. 内部链接

`static` 修饰的文件作用域变量/函数是内部链接，只在本编译单元可见：

```c
static int g_private;
static void helper(void) {}
```

其他文件写 `extern int g_private;` 也链接不到它——符号是 `LOCAL`，不参与跨文件解析。

### 3. C++ 的 const

C++ 命名空间作用域的 `const` 默认内部链接；要跨编译单元共享需显式 `extern`：

```cpp
// header
extern const int kMax;
// one .cpp
extern const int kMax = 100;
```

### 4. extern "C"

`extern "C"` 控制语言链接（符号名/调用约定），不是存储类说明符：

```cpp
extern "C" int c_api(int);
```

详见《C/C++ 语法差异与混编基础规则》。

## 四、弱符号的正确理解

弱符号不是"没有初始化的全局变量"。弱符号来自：

- `__attribute__((weak))` 显式标注；
- C++ 模板实例化、inline 函数的 COMDAT 弱符号；
- 编译器/链接器生成的内部弱符号。

```c
__attribute__((weak)) int g_default = 0;   // 弱定义
extern int optional_hook(void) __attribute__((weak));  // 弱引用
```

普通未初始化全局变量 `int g;` 在 C 中是**暂定定义**：

- 传统 GCC 放进 `COMMON` 段（`-fcommon`），链接器合并；
- GCC 10 起默认 `-fno-common`，它成为普通强定义，重复定义会报错。

所以不要把"未初始化"当成"弱符号"。

## 五、常见错误

### 1. multiple definition

```c
// header.h
int g_count = 0;    // 错误：头文件里定义
```

多个 `.cpp` 包含后各生成一份强定义。修复：头文件 `extern`，一个源文件定义；C++17 可用 `inline` 变量。

### 2. undefined reference

只有 `extern` 声明，没有定义，或定义所在源文件没有参与链接。修复：补定义、检查构建脚本、检查库顺序。

### 3. static 变量无法跨文件引用

`static` 是内部链接，其他文件无法通过 `extern` 引用。修复：去掉 static（并接受全局可见），或通过函数接口导出。

### 4. 头文件里 `static` 变量

```c
// header.h
static int g_state;   // 每个包含者各有一份，不是共享全局
```

这不是"跨文件共享"，而是每个编译单元一个独立副本。需要共享就用 `extern` + 单一定义。

### 5. C/C++ 混编符号不匹配

C++ 端缺少 `extern "C"`，按 mangled 名查找 C 符号，导致 undefined reference。

## 六、工程规范

1. 头文件只放声明，源文件放定义；
2. 全局变量命名加模块前缀，减少冲突；
3. 不需要跨文件访问的符号一律 `static`；
4. 头文件不用 `static` 定义变量/函数（除非明确要每 TU 一份）；
5. C++17 起常量可用 `inline constexpr`；
6. 混编接口加 `extern "C"`；
7. 用 `nm`、`-Wl,--trace-symbol` 检查符号来源。

## 七、面试简答

### 1. 声明和定义的区别？

定义分配存储或生成函数体，产生符号；声明只引入名字和类型，不分配存储。一个强符号只能有一个定义，声明可以有多处。

### 2. extern 的作用？

告诉编译器符号在别处定义，链接时再解析。它不分配内存，也不产生定义。

### 3. 未初始化的全局变量是弱符号吗？

不是。它是暂定定义：C 中传统上进入 COMMON（`-fcommon`），GCC 10 起默认 `-fno-common` 后成为普通强定义。弱符号需要 `__attribute__((weak))` 或 COMDAT 机制。

### 4. 为什么头文件里定义变量会多重定义？

头文件被文本复制进每个包含它的编译单元，每个单元都生成一份定义，链接时多个强定义冲突。修复是头文件 `extern`、源文件唯一定义。

## 八、极简口诀

**头文件声明 extern，源文件定义只一份；**

**static 内部链接，别的文件找不到；**

**未初始化非弱符号，-fno-common 变强定义；**

**混编加 extern "C"，nm 查符号来源。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
