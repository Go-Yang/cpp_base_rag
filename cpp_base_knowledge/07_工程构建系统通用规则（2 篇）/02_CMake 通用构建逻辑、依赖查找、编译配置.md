# CMake 通用构建逻辑、依赖查找、编译配置

## 一、前言

CMake 不是编译器，而是**构建系统生成器**：读取 `CMakeLists.txt`，生成 Makefile/Ninja/Visual Studio 工程，再调用底层构建工具。

核心总纲：**以 target 为中心，用 usage requirements 传递依赖。** 现代 CMake 的核心不是全局变量，而是 `target_*` 命令和 `PUBLIC/PRIVATE/INTERFACE` 传播。

## 二、最小工程

```cmake
cmake_minimum_required(VERSION 3.20)
project(myapp LANGUAGES C CXX)

add_executable(myapp
    src/main.cpp
    src/util.cpp
)

target_compile_features(myapp PRIVATE cxx_std_17)
target_include_directories(myapp PRIVATE include)
target_compile_options(myapp PRIVATE -Wall -Wextra)
target_link_libraries(myapp PRIVATE foo pthread m)
```

构建：

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
```

## 三、target 与传播

### 1. 创建 target

```cmake
add_executable(app main.cpp)
add_library(foo STATIC foo.cpp)
add_library(bar SHARED bar.cpp)
add_library(header_only INTERFACE)
```

### 2. usage requirements

```cmake
target_include_directories(foo
    PUBLIC  include          # 使用 foo 的人也需要
    PRIVATE src              # 只有 foo 自己需要
    INTERFACE api            # foo 自己不需要，但使用者需要
)

target_compile_definitions(foo PUBLIC FOO_ENABLED=1)
target_compile_options(foo PRIVATE -fno-exceptions)
target_link_libraries(foo PUBLIC bar PRIVATE baz)
```

| 关键字 | 自己用 | 使用者继承 |
|---|---|---|
| `PRIVATE` | 是 | 否 |
| `PUBLIC` | 是 | 是 |
| `INTERFACE` | 否 | 是 |

这是现代 CMake 最重要的概念：依赖关系随 target 传递，不需要手工拼全局 `include_directories`。

## 四、查找依赖

### 1. find_package

```cmake
find_package(Threads REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgproc)
find_package(Boost 1.80 REQUIRED COMPONENTS filesystem)

target_link_libraries(app PRIVATE
    Threads::Threads
    ${OpenCV_LIBS}
    Boost::filesystem
)
```

- Config 模式：库提供 `xxxConfig.cmake`，优先；
- Module 模式：CMake 自带 `Findxxx.cmake`；
- `REQUIRED`：找不到直接失败；
- `COMPONENTS`：只找需要的组件；
- 版本约束：`find_package(foo 1.2 REQUIRED)`。

### 2. pkg-config

```cmake
find_package(PkgConfig REQUIRED)
pkg_check_modules(GTK3 REQUIRED gtk+-3.0)

target_include_directories(app PRIVATE ${GTK3_INCLUDE_DIRS})
target_link_libraries(app PRIVATE ${GTK3_LIBRARIES})
```

### 3. FetchContent

```cmake
include(FetchContent)
FetchContent_Declare(
    fmt
    GIT_REPOSITORY https://github.com/fmtlib/fmt.git
    GIT_TAG 10.2.1
)
FetchContent_MakeAvailable(fmt)

target_link_libraries(app PRIVATE fmt::fmt)
```

适合没有系统包或需要固定版本的依赖；注意网络和构建时间。

## 五、编译配置

### 1. 构建类型

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
```

- 单配置生成器（Makefiles/Ninja）：`CMAKE_BUILD_TYPE` 有效；
- 多配置生成器（VS/Xcode）：用 `--config Debug`；
- 常见类型：Debug、Release、RelWithDebInfo、MinSizeRel。

### 2. 编译选项

```cmake
target_compile_options(app PRIVATE
    $<$<CONFIG:Debug>:-O0;-g>
    $<$<CONFIG:Release>:-O2>
)
```

生成器表达式按配置/平台条件化选项，避免污染所有构建。

### 3. C++ 标准

```cmake
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# 或按 target：
target_compile_features(app PRIVATE cxx_std_17)
```

### 4. 位置无关代码

```cmake
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
# 或
set_target_properties(foo PROPERTIES POSITION_INDEPENDENT_CODE ON)
```

共享库通常需要 `-fPIC`；静态库被链接进共享库时也需要。

## 六、安装与导出

```cmake
include(GNUInstallDirs)

install(TARGETS app foo
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
```

```bash
cmake --install build --prefix /opt/myapp
```

对外提供库时，用 `install(EXPORT ...)` 和 `fooConfig.cmake` 导出 target，使用者可以 `find_package(foo)` 并 `target_link_libraries(app PRIVATE foo::foo)`。

## 七、RPATH

```cmake
set(CMAKE_INSTALL_RPATH "$ORIGIN/../lib")
set(CMAKE_BUILD_WITH_INSTALL_RPATH OFF)
set(CMAKE_INSTALL_RPATH_USE_LINK_PATH ON)
```

- 构建树和安装树的 rpath 要分开；
- `$ORIGIN` 以可执行文件位置为基准；
- 发布时避免把构建机绝对路径写进 rpath。

## 八、交叉编译

工具链文件：

```cmake
# toolchain-aarch64.cmake
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
set(CMAKE_FIND_ROOT_PATH /opt/aarch64-sysroot)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
```

```bash
cmake -S . -B build-arm -DCMAKE_TOOLCHAIN_FILE=toolchain-aarch64.cmake
```

## 九、CMakePresets

```json
{
  "version": 6,
  "configurePresets": [
    {
      "name": "debug",
      "generator": "Ninja",
      "binaryDir": "${sourceDir}/build/debug",
      "cacheVariables": { "CMAKE_BUILD_TYPE": "Debug" }
    }
  ]
}
```

```bash
cmake --preset debug
cmake --build --preset debug
```

把构建配置固化到仓库，避免每个人手敲不同参数。

## 十、常见问题

### 1. 全局 include_directories 污染

优先 `target_include_directories`，避免所有 target 互相看到头文件。

### 2. 依赖没有传递

静态库 A 依赖 B，但只写了 `target_link_libraries(app PRIVATE A)`。如果 A 用 `PRIVATE` 链接 B，app 不会继承 B；A 的公共接口依赖 B 时应使用 `PUBLIC`。

### 3. 找不到包

- `find_package` 模式不对（Config vs Module）；
- 缺少 `-DCMAKE_PREFIX_PATH=/path`；
- 包没安装或版本不匹配；
- 交叉编译时 find root path 设置错误。

### 4. 多配置生成器下 CMAKE_BUILD_TYPE 无效

VS/Xcode 是多配置生成器，应使用 `--config Release`，而不是 `CMAKE_BUILD_TYPE`。

### 5. 共享库符号未导出

默认符号可见性、`-fvisibility=hidden`、缺少导出宏。用 `target_compile_definitions` 控制导出。

### 6. RPATH 指向构建目录

安装后找不到库。设置 `CMAKE_INSTALL_RPATH`，避免把构建路径写死。

### 7. 编译选项没有生效

用 `target_compile_options` 而不是全局 `add_compile_options`；检查生成器表达式和配置类型。

## 十一、面试标准简答

### 1. CMake 的 PUBLIC/PRIVATE/INTERFACE 有什么区别？

`PRIVATE` 只用于当前 target；`PUBLIC` 当前 target 用，且传递给链接它的 target；`INTERFACE` 当前 target 不用，只传递给使用者。它们描述依赖的传播方式。

### 2. find_package 的 Config 和 Module 模式？

Config 模式找库自带的 `xxxConfig.cmake`，信息最准确；Module 模式用 CMake 自带的 `Findxxx.cmake` 或用户提供的查找脚本。优先 Config。

### 3. 为什么推荐 target_* 而不是全局命令？

target 级别的作用域清晰，依赖随 target 传播，避免全局污染和隐式耦合；全局命令容易让所有 target 共享不该共享的头文件/宏/选项。

### 4. 如何做交叉编译？

编写 toolchain 文件，指定 `CMAKE_SYSTEM_NAME`、编译器、sysroot 和 find root path 模式，配置时传入 `-DCMAKE_TOOLCHAIN_FILE=...`。

## 十二、极简口诀

**CMake 生成构建，target 是核心；**

**PUBLIC 传、PRIVATE 留、INTERFACE 只给用的人；**

**find_package 找依赖，生成器表达式分配置；**

**install 配 rpath，toolchain 做交叉。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
