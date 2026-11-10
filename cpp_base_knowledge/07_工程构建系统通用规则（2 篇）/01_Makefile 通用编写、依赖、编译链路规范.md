# Makefile 通用编写、依赖、编译链路规范

## 一、前言

Make 的核心模型只有一句话：

```text
目标: 依赖
<TAB>命令
```

- 目标比依赖旧（或目标不存在）→ 执行命令；
- 依赖又依赖其他目标 → 递归构建。

核心总纲：**目标 + 依赖 + 命令构成 DAG；依赖关系写对，增量编译才正确。** 大多数 Makefile 问题不是语法，而是依赖漏写、变量用错、库顺序不对。

## 二、基础语法

### 1. 规则

```make
app: main.o util.o
	gcc main.o util.o -o app
```

- 命令必须以 **TAB** 开头（不是空格）；
- 目标不一定要生成文件（伪目标）。

### 2. 变量

```make
CC      := gcc
CXX     := g++
CFLAGS  := -Wall -Wextra -O2 -g
CPPFLAGS:= -Iinclude -DDEBUG
LDFLAGS := -Llib
LDLIBS  := -lfoo -lm

$(CC) $(CFLAGS) $(CPPFLAGS) -c foo.c -o foo.o
```

赋值方式：

| 写法 | 含义 |
|---|---|
| `=` | 递归展开，使用时才求值 |
| `:=` | 立即展开 |
| `?=` | 未定义才赋值 |
| `+=` | 追加 |
| `override` | 覆盖命令行传入的变量 |

### 3. 自动变量

| 变量 | 含义 |
|---|---|
| `$@` | 目标名 |
| `$<` | 第一个依赖 |
| `$^` | 所有依赖（去重） |
| `$?` | 比目标新的依赖 |
| `$*` | 模式规则中的词干 |
| `$(@D)` / `$(@F)` | 目标目录/文件名 |

### 4. 模式规则

```make
%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@
```

等价于为每个 `.c` 生成对应的编译规则。

### 5. 函数

```make
SRCS := $(wildcard src/*.c)
OBJS := $(SRCS:.c=.o)
OBJS := $(patsubst src/%.c,build/%.o,$(SRCS))
DIRS := $(sort $(dir $(OBJS)))
```

## 三、完整示例

```make
CC       := gcc
CFLAGS   := -Wall -Wextra -O2 -g -MMD -MP
CPPFLAGS := -Iinclude
LDFLAGS  := -Llib
LDLIBS   := -lfoo -lpthread -lm

TARGET   := app
SRCS     := $(wildcard src/*.c)
OBJS     := $(patsubst src/%.c,build/%.o,$(SRCS))
DEPS     := $(OBJS:.o=.d)

.PHONY: all clean install

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(LDFLAGS) $^ $(LDLIBS) -o $@

build/%.o: src/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

-include $(DEPS)

clean:
	rm -rf build $(TARGET)

install: $(TARGET)
	install -D -m 755 $(TARGET) $(DESTDIR)/usr/local/bin/$(TARGET)
```

关键点：

- `-MMD -MP` 生成头文件依赖（`.d`），`-include` 引入；
- `$^` 保证所有对象文件参与链接；
- `LDLIBS` 放在对象文件之后，保证库顺序；
- `.PHONY` 防止 `all`/`clean` 与同名文件冲突；
- `mkdir -p` 支持嵌套输出目录。

## 四、依赖管理

### 1. 为什么需要头文件依赖

如果只写 `main.o: main.c`，修改 `main.c` 包含的头文件不会触发重编，产物可能过期。

### 2. 自动依赖

```make
CFLAGS += -MMD -MP
-include $(DEPS)
```

- `-MMD`：生成 `.d` 文件，记录用户头文件依赖；
- `-MP`：为每个头文件生成空目标，避免删除头文件后报错；
- `-include`：文件不存在时不报错（首次构建）。

### 3. 依赖方向

- 目标依赖源文件和头文件；
- 最终目标依赖所有 `.o`；
- 库依赖顺序见下面的链接部分。

## 五、链接与库顺序

Makefile 传参顺序会成为链接器参数顺序：

```make
$(TARGET): $(OBJS)
	$(CC) $(LDFLAGS) $^ $(LDLIBS) -o $@
```

- 对象文件在库前面；
- 静态库依赖方在前、被依赖方在后；
- `LDLIBS` 通常放最后；
- 循环依赖用 `-Wl,--start-group ... -Wl,--end-group`。

## 六、并行与目录

```bash
make -j8
```

- `-j` 并行构建，要求依赖关系完整；
- 目录创建用 order-only 依赖避免每次重建：

```make
$(OBJS): | build

build:
	mkdir -p build
```

`|` 后面是 order-only 依赖：目录不存在才创建，目录时间戳变化不触发重编。

## 七、调试 Makefile

```bash
make -n            # 只打印命令不执行
make --debug=v     # 调试依赖决策
make -p            # 打印所有规则和变量
make V=1           # 自定义 verbose 变量
```

在规则里加 `@` 隐藏命令，`$(info ...)` 打印变量，`$(warning ...)` 输出警告。

## 八、常见错误

### 1. 命令用空格缩进

```text
Makefile:5: *** missing separator. Stop.
```

必须用 TAB。

### 2. 依赖漏写

改了头文件没重编。用 `-MMD -MP`。

### 3. 用 gcc 链接 C++ 目标文件

`std::cout` 等符号缺失。C++ 项目用 `$(CXX)` 链接，并加 `-lstdc++`（通常自动）。

### 4. 库顺序错误

`undefined reference`。把 `LDLIBS` 放在对象之后，按依赖顺序排列。

### 5. 目标不是 .PHONY

目录下存在同名文件时，`make clean` 不执行。加 `.PHONY: clean`。

### 6. 变量展开时机错误

用 `=` 导致每次求值，或在规则里意外展开 shell 命令。需要立即求值用 `:=`。

### 7. 并行构建竞争

多个规则同时写同一文件、目录创建竞争。用 order-only 依赖和唯一输出路径。

## 九、面试标准简答

### 1. Makefile 的基本结构？

规则由目标、依赖、命令组成；目标比依赖旧时执行命令。变量和模式规则减少重复，`.PHONY` 标记伪目标，`-include` 引入自动生成的依赖文件。

### 2. 如何让 Makefile 正确处理头文件依赖？

编译时加 `-MMD -MP` 生成 `.d` 文件，用 `-include $(DEPS)` 引入。这样头文件变化会触发依赖它的源文件重编。

### 3. 为什么库要放在对象文件后面？

链接器从左到右扫描，静态库只解析当前未定义符号。库放在对象后面，才能看到对象引入的未定义符号；顺序还要遵循依赖方在前。

### 4. `:=` 和 `=` 的区别？

`:=` 在定义时立即展开；`=` 在使用时递归展开。需要固定值或避免重复求值时用 `:=`。

## 十、极简口诀

**目标依赖 TAB 命令，DAG 决定谁先编；**

**变量自动 $@ $< $^，模式规则省重复；**

**-MMD -MP 管头文件，库放对象后；**

**伪目标 .PHONY，调试 make -n。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
