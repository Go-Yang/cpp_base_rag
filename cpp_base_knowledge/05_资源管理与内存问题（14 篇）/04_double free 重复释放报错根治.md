# double free 重复释放报错根治

## 一、前言

`double free` 是对同一块堆内存释放两次。glibc 的典型报错：

```text
free(): double free detected in tcache 2
free(): invalid pointer
double free or corruption (out)
munmap_chunk(): invalid pointer
```

核心总纲：**double free = 所有权不唯一。** 只要一块内存有多个"我负责释放"的所有者，就迟早会重复释放。根治靠所有权设计，不是靠加判断。

## 二、底层原理

### 1. 分配器如何检测

glibc malloc 在 chunk 头里记录大小和状态。释放时：

- 检查指针是否对齐、是否指向合法 chunk；
- 检查 chunk 是否已经在 bin/tcache 中（tcache key、fastbin 链表头）；
- 检查相邻 chunk 的元数据是否一致。

检测到异常就 `abort`，输出上面的报错。没有检测到的 double free 可能悄悄破坏链表，等到后续分配/释放才崩。

### 2. 为什么危害大

- 同一块进入空闲链表两次，之后可能被分配给两个不同的请求；
- 两个对象共享同一内存，互相覆盖；
- 攻击者可利用它构造任意地址写（堆利用的经典原语）。

## 三、常见成因

### 1. 多个所有者

```c
Foo* p = create();
module_a_owns(p);   // A 认为归它释放
module_b_owns(p);   // B 也认为归它释放
```

### 2. 错误路径重复释放

```c
if (error) {
    free(p);
}
// ...
free(p);            // 正常路径又释放一次
```

### 3. 指针别名

```c
Foo* a = obj;
Foo* b = obj;
free(a);
free(b);            // 同一块
```

### 4. 析构函数 + 手动释放

```cpp
Foo* p = new Foo;
delete p;
p->~Foo();          // 再析构一次
```

### 5. 智能指针 + 裸指针混用

```cpp
Foo* raw = new Foo;
std::shared_ptr<Foo> sp(raw);
delete raw;          // 双重所有权，必然 double free
```

### 6. 两个 shared_ptr 从同一裸指针构造

```cpp
Foo* raw = new Foo;
std::shared_ptr<Foo> a(raw);
std::shared_ptr<Foo> b(raw);   // 两个独立控制块，各自 delete 一次
```

正确写法：`auto a = std::make_shared<Foo>(); auto b = a;`

### 7. 异常/回调导致重复清理

回调里释放了对象，主流程又释放一次。

### 8. 结构体里的指针被拷贝

浅拷贝导致两个对象持有同一指针，析构各释放一次。需要深拷贝或明确所有权（Rule of Five / 移动语义）。

## 四、定位手段

### 1. ASAN（首选）

```bash
gcc -fsanitize=address -fno-omit-frame-pointer -g app.c -o app
```

ASAN 会直接报：

```text
attempting double-free on 0x...
previously freed by thread T0 here:
    #0 free
    #1 foo app.c:42
```

同时给出第一次释放和第二次释放的完整调用栈。

### 2. Valgrind

```bash
valgrind --tool=memcheck ./app
```

报 `Invalid free()`，并给出两次释放的位置。

### 3. glibc 自身

- `MALLOC_CHECK_=3` 加强检查；
- tcache 报错信息通常能指出大小类；
- 用 gdb 在 `free` 上下断点，记录每个指针。

### 4. 代码审查

- 搜索所有 `free` / `delete`；
- 标记每块内存的所有权；
- 检查拷贝构造/赋值是否浅拷贝；
- 检查错误路径是否和正常路径重复释放。

## 五、根治方案

1. **单一所有权**：一块内存只有一个明确的释放者。
2. **RAII**：`std::unique_ptr`、`std::shared_ptr`、`std::vector`、`std::string`。
3. **释放后置空**仅对单指针有效，别名问题仍需所有权设计。
4. **禁止裸指针拥有所有权**：函数参数用引用/`T*` 表示借用，所有权用智能指针。
5. **遵守 Rule of Five**：自定义析构的类，拷贝/移动要配套，或直接禁用拷贝。
6. **不要智能指针和裸 delete 混用**。
7. **回调注销**：对象销毁前注销所有回调。
8. **CI 跑 ASAN**，让 double free 在测试阶段暴露。

## 六、排查流程

1. 用 ASAN 复现，拿到两次释放的调用栈；
2. 确认这块内存的所有者是谁；
3. 找出为什么会有第二个所有者（别名、拷贝、错误路径、回调）；
4. 改为单一所有权或智能指针；
5. 回归测试 + ASAN 验证。

## 七、面试标准简答

### 1. double free 为什么危险？

同一块内存被释放两次，会破坏分配器的空闲链表。之后它可能被分配给两个请求，导致两个对象共享同一内存，产生任意写、信息泄漏甚至代码执行。

### 2. 如何彻底避免 double free？

明确单一所有权，使用 RAII/智能指针，禁止裸指针拥有所有权，遵守 Rule of Five，避免智能指针与手动 delete 混用，对象销毁前注销回调。

### 3. free 后置 NULL 能防止 double free 吗？

只能防止通过同一个指针变量再次 free；别名指针仍然指向已释放内存，照样会 double free 或 use-after-free。根本方法是所有权唯一。

### 4. 两个 shared_ptr 从同一裸指针构造会怎样？

它们各自创建独立的控制块，引用计数互不相干，析构时各自 delete 一次，导致 double free。应使用 `make_shared` 或从一个已有的 shared_ptr 拷贝构造。

## 八、极简口诀

**double free 因多主，一块内存多人放；**

**别名、浅拷贝、错路径，智能指针混裸针；**

**ASAN 给两栈，所有权要唯一；**

**析构配对拷贝移，回调先注销。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
