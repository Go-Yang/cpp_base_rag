# const、static、volatile底层修饰原理

## 一、前言

`const`、`static`、`volatile` 经常被放在一起讲，但它们控制的是三件不同的事：

- `static`：**链接属性与存储期**（谁能看见、活多久）；
- `const`：**只读约束**（能不能通过这个名字修改）；
- `volatile`：**访问语义**（编译器能不能缓存/优化这次读写）。

核心总纲：**static 管可见性和生命周期，const 管写权限，volatile 管访问方式。三者互不替代，尤其是 volatile 不能当线程同步用。**

## 二、static

### 1. static 修饰文件作用域变量/函数

```c
// a.c
static int g_count;          // 内部链接，只在本编译单元可见
static void helper(void) {}  // 内部链接
```

- 符号在目标文件里是 `LOCAL`（`nm` 显示小写 `b`/`t`）；
- 其他编译单元不能用 `extern` 引用；
- 变量仍在 `.data`/`.bss`，函数在 `.text`；
- 用途：文件私有实现，避免全局命名冲突。

注意：`static` 符号仍然存在于符号表中（`LOCAL`），只是不参与跨文件符号解析。说"不进入符号表"是不准确的。

### 2. static 修饰局部变量

```c
void count(void) {
    static int n = 0;   // 静态存储期，作用域仍在本函数
    n++;
}
```

- 存储在 `.data`/`.bss`，不是栈；
- 程序加载时分配存储；
- C 中常量初值在 `main` 之前完成；C++ 中动态初值在**第一次执行到声明处**初始化；
- C++11 起，函数内 static 的初始化是线程安全的（编译器生成 guard 变量）；
- 初始化完成后的读写仍然需要同步；static 不等于线程安全。

### 3. static 成员（C++）

```cpp
struct Counter {
    static int total;        // 所有对象共享，需要在类外定义
    static int get();        // 没有 this 指针
};
int Counter::total = 0;
```

- 静态成员属于类，不属于对象；
- C++17 起可以用 `inline static int total = 0;` 在类内定义；
- 静态成员函数不能访问非静态成员。

### 4. static 的常见坑

- 多线程共享 static 变量，无锁读写是数据竞争；
- 函数内 static 的状态会跨调用保留，逻辑依赖调用顺序时容易出 bug；
- 头文件里定义 `static` 变量/函数，会让每个包含它的编译单元各有一份副本，增加体积，且不是"全局共享"；
- 不要用 static 掩盖本该通过参数传递的依赖。

## 三、const

### 1. const 是只读约束，不一定是编译期常量

```cpp
const int a = 10;      // 常量表达式，可用于数组大小
const int b = rand();  // 运行期初始化，不是常量表达式
```

- `const` 表示"通过这个名字不能修改"；
- C++ 中只有用常量表达式初始化的 `const` 才能用于需要常量表达式的地方；
- 不要把所有 `const` 都当成编译期常量。

### 2. const 与链接属性（C/C++ 差异）

- C：文件作用域 `const` 默认是**外部链接**（类似普通全局变量）；
- C++：命名空间作用域 `const` 默认是**内部链接**（相当于加了 static）；
- C++ 中如果需要跨编译单元共享，写 `extern const int x = 10;` 并在头文件声明。

### 3. 存储位置

- 全局 `const` 常量通常放 `.rodata`（只读数据段）；
- 局部 `const` 可能在栈上、寄存器中或被立即数折叠，取决于编译器和优化；
- 字符串字面量在 `.rodata`，写入是未定义行为/段错误；
- `const` 成员、`constexpr` 变量通常没有运行时存储（被折叠），但取地址时会有实体。

### 4. 修改 const 对象是未定义行为

```cpp
const int x = 10;
const_cast<int&>(x) = 20;   // UB：x 本身是 const 对象
```

如果对象本身不是 const，只是通过 const 指针/引用访问，去掉 const 后修改是允许的：

```cpp
int y = 10;
const int* p = &y;
*const_cast<int*>(p) = 20;  // 合法，y 本身不是 const
```

### 5. const 指针的两种语义

```c
const int* p1;        // 指向常量的指针：*p1 不可改，p1 可改
int* const p2 = &x;   // 常量指针：p2 不可改，*p2 可改
const int* const p3;  // 两者都不可改
```

记忆：**const 在 `*` 左边修饰指向的数据，在 `*` 右边修饰指针本身。**

### 6. C++ 的 const 成员函数与 mutable

```cpp
class Buffer {
    mutable size_t cache_hits_ = 0;
public:
    size_t size() const {           // 承诺不修改对象的可见状态
        ++cache_hits_;              // mutable 成员允许修改
        return size_;
    }
};
```

- `const` 成员函数里 `this` 是 `const T*`；
- `mutable` 用于逻辑上不改变对象状态的缓存/计数器；
- 不要滥用 `mutable` 破坏 const 语义。

## 四、volatile

### 1. volatile 的语义

`volatile` 告诉编译器：这个对象的读写是**可观察的副作用**，可能被程序之外的因素改变，因此：

- 不能把变量缓存在寄存器里跨多次访问；
- 不能删除"看起来没用"的读写；
- 编译器对 volatile 访问之间的顺序有一定约束。

### 2. 正确用途

- **内存映射 I/O（MMIO）**：硬件寄存器地址；
- **信号处理函数**中与主程序共享的 `volatile sig_atomic_t` 变量；
- `setjmp`/`longjmp` 之间可能被修改的局部变量；
- 与外部硬件/中断交互的特殊内存。

```c
volatile uint32_t* reg = (volatile uint32_t*)0x40000000;
*reg = 1;          // 必须真正写内存
while (*reg & 1) { // 每次都重新读
}
```

### 3. volatile 不能用于线程同步

这是最常见的误区：

- `volatile` 不保证原子性（`counter++` 仍然不是原子操作）；
- 不建立 happens-before 关系；
- 不阻止 CPU 层面的重排；
- C/C++ 内存模型中，未同步的并发读写是**数据竞争**，属于未定义行为。

```cpp
volatile bool ready = false;   // 错误：不是同步
// 线程 A: data = 42; ready = true;
// 线程 B: while (!ready) {} use(data);
```

正确写法：`std::atomic<bool>` + acquire/release，或用互斥锁。

### 4. volatile 与 const 组合

```c
const volatile uint32_t* status;  // 程序只读、硬件可改的状态寄存器
```

- `const` 禁止程序写入；
- `volatile` 强制每次读取都访问内存；
- 典型用于只读硬件状态寄存器。

## 五、三者组合速查

| 组合 | 含义 | 典型场景 |
|---|---|---|
| `static` 全局变量 | 文件私有、静态存储期 | 模块内部状态 |
| `static` 局部变量 | 函数作用域、静态存储期 | 调用计数、缓存 |
| `static const` | 文件私有只读常量 | 模块常量表 |
| `const` 全局 | 只读，C++ 默认内部链接 | 常量配置 |
| `constexpr`（C++） | 编译期常量 | 数组大小、模板参数 |
| `volatile` | 每次访问内存 | MMIO、信号处理 |
| `const volatile` | 程序只读、外部可改 | 硬件状态寄存器 |

## 六、常见面试简答

### 1. static 的作用？

修饰文件作用域变量/函数时改为内部链接，只在本编译单元可见；修饰局部变量时改为静态存储期，函数返回后仍保留；修饰类成员时属于类而不是对象。static 不改变变量的作用域（局部 static 仍只在函数内可见）。

### 2. const 和 constexpr 的区别？

`const` 只保证通过该名字不可修改，不保证编译期可求值；`constexpr` 要求编译期可求值（C++11 起，C++14 放宽了函数体限制），可用于数组大小、模板参数等常量表达式场景。

### 3. volatile 能保证线程安全吗？

不能。volatile 只阻止编译器对该对象的某些优化，不提供原子性、内存屏障或 happens-before。线程间同步必须用 `std::atomic`、互斥锁或条件变量。

### 4. const 对象被 const_cast 修改会怎样？

如果对象本身定义为 const，修改它是未定义行为；如果对象本身不是 const，只是通过 const 指针/引用访问，去掉 const 后修改是合法的。

## 七、极简口诀

**static 管链接和存储，const 管只读，volatile 管访问；**

**局部 static 不在栈，C++ 首次执行才构造；**

**const 不等于常量表达式，改 const 对象是 UB；**

**volatile 不是锁，线程同步用原子/互斥。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
