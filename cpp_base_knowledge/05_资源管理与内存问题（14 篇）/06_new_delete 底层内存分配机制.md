# new/delete 底层内存分配机制

## 一、前言

`new` 和 `delete` 不是简单的"分配/释放内存"，它们各自包含两个动作：

- `new T`：分配内存（`operator new`） + 构造对象（placement new）；
- `delete p`：析构对象（`~T()`） + 释放内存（`operator delete`）。

核心总纲：**new/delete = 内存管理 + 对象生命周期。** `malloc/free` 只管内存，不管构造/析构，这是两者最本质的区别。

## 二、new 的完整过程

### 1. 单个对象

```cpp
Foo* p = new Foo(42);
```

编译器展开为：

```cpp
void* mem = operator new(sizeof(Foo));   // 分配
Foo* p;
try {
    p = new (mem) Foo(42);               // placement new，调用构造函数
} catch (...) {
    operator delete(mem);                // 构造抛异常，自动释放
    throw;
}
```

关键点：

- `operator new` 默认调用 `malloc`；
- 构造失败（抛异常）时，编译器自动调用 `operator delete`，不会泄漏；
- 分配失败时，默认抛 `std::bad_alloc`。

### 2. 数组

```cpp
Foo* arr = new Foo[10];
```

- 分配时可能多一个 **array cookie**，记录元素个数（供 `delete[]` 调用正确次数的析构）；
- 依次构造 10 个对象；
- 某个构造抛异常时，已构造的对象会被逐个析构，再释放内存。

### 3. nothrow 版本

```cpp
Foo* p = new (std::nothrow) Foo;
if (!p) { /* 分配失败，返回 nullptr */ }
```

`malloc` 失败返回 NULL；普通 `new` 失败抛异常。

### 4. 定位 new（placement new）

```cpp
alignas(Foo) unsigned char buf[sizeof(Foo)];
Foo* p = new (buf) Foo(42);   // 在指定内存上构造，不分配
p->~Foo();                     // 必须手动析构
```

用于内存池、容器、共享内存等。它不调用 `operator new`，也不负责释放。

## 三、delete 的完整过程

### 1. 单个对象

```cpp
delete p;
```

展开为：

```cpp
if (p != nullptr) {
    p->~Foo();                    // 析构
    operator delete(p);           // 释放内存
}
```

- `delete nullptr` 安全，不做任何事；
- 析构函数如果是 virtual，会正确调用派生类析构。

### 2. 数组

```cpp
delete[] arr;
```

- 读取 array cookie，得到元素个数；
- 逆序析构每个元素；
- 调用 `operator delete[]` 释放整块内存。

### 3. 不匹配的后果

```cpp
Foo* arr = new Foo[10];
delete arr;      // UB：只析构一个，释放方式也可能不对
```

`new[]` 必须配 `delete[]`；`new` 必须配 `delete`。不匹配是未定义行为，常见表现是泄漏、崩溃、堆损坏。

## 四、operator new / delete 可替换

### 1. 全局替换

```cpp
void* operator new(std::size_t size) {
    void* p = std::malloc(size);
    if (!p) throw std::bad_alloc();
    return p;
}

void operator delete(void* p) noexcept {
    std::free(p);
}
```

可以替换全局版本，接入内存池、统计、对齐分配。

### 2. 类内重载

```cpp
struct Foo {
    static void* operator new(std::size_t size);
    static void operator delete(void* p) noexcept;
};
```

只影响 `Foo` 的 `new`/`delete`，适合固定大小对象的池化。

### 3. 对齐版本（C++17）

```cpp
void* operator new(std::size_t size, std::align_val_t align);
```

用于过度对齐类型（如 SIMD、缓存行对齐）。

### 4. 数组版本

可以分别重载 `operator new[]` / `operator delete[]`。

## 五、异常与构造顺序

- 构造函数抛异常：已分配的内存由编译器自动释放（调用匹配的 `operator delete`）；
- 数组构造中途抛异常：已构造元素逆序析构，然后释放内存；
- 析构函数不应抛异常（`noexcept` 默认），否则可能 `std::terminate`；
- 派生类构造失败时，基类已构造部分会自动析构。

## 六、new/delete 与 malloc/free 对比

| 维度 | new/delete | malloc/free |
|---|---|---|
| 语言 | C++ 运算符 | C 函数 |
| 构造/析构 | 调用 | 不调用 |
| 失败行为 | 抛 `bad_alloc`（nothrow 返回 NULL） | 返回 NULL |
| 大小 | 编译器计算 | 手动传入 |
| 类型 | 返回正确类型指针 | `void*` |
| 数组 | `new[]`/`delete[]` | 手动计算字节数 |
| 可重载 | 是 | 否 |
| 底层 | 通常调用 malloc | 系统分配器 |

不要混用：`new` 的内存用 `free` 释放、`malloc` 的内存用 `delete` 释放，都是未定义行为。

## 七、常见问题

### 1. 构造抛异常会泄漏吗

不会。编译器生成的代码会捕获异常并调用对应的 `operator delete`。前提是使用正常的 `new` 表达式，而不是手工 `operator new` + placement new。

### 2. delete 基类指针为什么必须虚析构

非虚析构只调用基类析构，派生类资源泄漏；更严重的是 `operator delete` 可能用错大小/地址，导致堆损坏。

### 3. new[] 的 cookie 是什么

编译器为数组额外存储元素个数，`delete[]` 靠它决定析构多少次、如何释放。对没有非平凡析构的类型，编译器可能省略 cookie。

### 4. 为什么建议用 make_unique/make_shared

它们把分配和构造放在一个表达式里，异常安全；`make_shared` 还能把控制块和对象合并为一次分配。

## 八、面试标准简答

### 1. new 和 malloc 的区别？

`new` 是运算符，分配内存并调用构造函数，失败抛异常，返回类型化指针，可重载；`malloc` 是函数，只分配原始内存，失败返回 NULL，需要手动计算大小和类型转换。

### 2. delete 和 free 的区别？

`delete` 先调用析构函数再释放内存，支持虚析构和数组形式；`free` 只释放内存。两者不能混用。

### 3. new[] 和 delete[] 为什么必须配对？

`new[]` 可能有 array cookie 记录元素个数，`delete[]` 需要它来析构所有元素并按正确方式释放。用 `delete` 释放 `new[]` 是未定义行为。

### 4. 构造函数抛异常会内存泄漏吗？

不会。`new` 表达式会保证在构造失败时调用匹配的 `operator delete`；数组构造失败还会析构已构造的元素。手工 placement new 需要自己处理。

## 九、极简口诀

**new 两步：分配加构造；delete 两步：析构加释放；**

**new[] 配 delete[]，cookie 记个数；**

**构造抛异常，编译器自动释放；**

**new/free 不混用，基类析构要 virtual。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
