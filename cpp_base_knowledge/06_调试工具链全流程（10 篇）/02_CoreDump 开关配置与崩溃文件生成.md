# CoreDump 开关配置与崩溃文件生成

## 一、前言

CoreDump 是进程崩溃时内核生成的**内存快照**，包含崩溃现场的寄存器、栈、内存映射和信号信息。它是事后调试的核心材料。

核心总纲：**core 能不能生成，取决于资源限制、core_pattern、进程 dumpable 和容器配置。** 任何一环不满足，崩溃后都只剩一句 "Segmentation fault"。

## 二、生成条件

### 1. RLIMIT_CORE

```bash
ulimit -c            # 0 表示不生成
ulimit -c unlimited  # 临时打开
```

- 软限制为 0 时，任何 core 都不会生成；
- 只对当前 shell 及其子进程生效；
- 永久修改：`/etc/security/limits.conf`、systemd `LimitCORE`。

### 2. core_pattern

```bash
cat /proc/sys/kernel/core_pattern
```

常见值：

| 值 | 含义 |
|---|---|
| `core` | 当前目录下生成 `core` |
| `core.%p` | 带 PID |
| `/var/crash/core.%e.%p.%t` | 指定目录和命名 |
| `|/usr/lib/systemd/systemd-coredump %P %u %g %s %t %c %h` | 管道给 systemd-coredump |
| `|/usr/share/apport/apport ...` | Ubuntu apport |

如果以 `|` 开头，内核把 core 通过管道交给用户态程序处理，文件位置由该程序决定。

### 3. 进程 dumpable

- setuid/setgid 程序默认不可 dump；
- 调用 `prctl(PR_SET_DUMPABLE, 0)` 后不可 dump；
- `/proc/sys/fs/suid_dumpable` 控制 setuid 程序是否允许 core（0/1/2）。

```c
#include <sys/prctl.h>
prctl(PR_SET_DUMPABLE, 1);
```

### 4. 其他限制

- 磁盘空间不足；
- core 大小超过 `RLIMIT_CORE`；
- 容器 `ulimit -c` 为 0；
- 某些沙箱/安全策略禁止 core；
- SIGKILL 的默认动作是终止进程，不产生 core；进程也没有机会做任何用户态清理。

## 三、开启方式

### 1. Shell 临时开启

```bash
ulimit -c unlimited
./app
```

### 2. 代码内设置

```c
#include <sys/resource.h>

struct rlimit rl = { RLIM_INFINITY, RLIM_INFINITY };
setrlimit(RLIMIT_CORE, &rl);
```

### 3. systemd 服务

```ini
[Service]
LimitCORE=infinity
```

### 4. 容器

```bash
docker run --ulimit core=-1 ...
```

同时确认宿主机 `core_pattern` 和存储目录可写。

## 四、core 文件在哪里

### 1. 直接生成

`core_pattern` 不以 `|` 开头时：

- 相对路径：相对于进程当前工作目录；
- 绝对路径：写到指定目录；
- 需要目录存在且可写。

### 2. systemd-coredump

```bash
coredumpctl list
coredumpctl info <pid>
coredumpctl debug <pid>
```

core 存在 `/var/lib/systemd/coredump/`，用 `coredumpctl` 访问。

### 3. apport（Ubuntu）

core 存在 `/var/crash/`，用 `apport-unpack` 提取。

## 五、验证与使用

```bash
file core
readelf -n core | head
gdb ./app core
(gdb) bt
(gdb) info registers
```

core 必须与**生成它时的二进制**匹配；版本不一致时栈和符号会错位。保留 build-id 对应关系：

```bash
readelf -n app | grep 'Build ID'
readelf -n core | grep 'Build ID'
```

## 六、命名与清理

`core_pattern` 常用占位符：

| 占位符 | 含义 |
|---|---|
| `%p` | PID |
| `%e` | 可执行文件名 |
| `%t` | 时间戳 |
| `%u` | UID |
| `%g` | GID |
| `%s` | 触发信号 |
| `%c` | core 大小限制 |
| `%h` | 主机名 |

建议包含 `%e.%p.%t`，避免互相覆盖；配置定期清理，防止磁盘被 core 占满。

## 七、常见问题

### 1. 崩溃了但没有 core

按顺序检查：

1. `ulimit -c` 是否为 0；
2. `core_pattern` 是否指向可写路径；
3. 进程是否 dumpable（setuid、prctl）；
4. 容器/服务是否限制；
5. 磁盘是否满；
6. 信号是否会产生 core（SIGKILL 不产生）。

### 2. core 生成在奇怪的位置

相对路径基于崩溃进程的 cwd，不一定是你启动 shell 的目录。用绝对路径或 `|` 管道。

### 3. gdb 打开 core 提示不匹配

二进制版本不对，或缺少调试符号。用 build-id 找对应版本和 `.debug` 文件。

### 4. 容器里没有 core

容器默认 `ulimit -c 0`，且 `core_pattern` 是宿主机全局设置。启动容器时加 `--ulimit core=-1`，并确认宿主机路径。

### 5. core 文件太大

core 包含整个地址空间。可以：

- 限制 `RLIMIT_CORE` 大小；
- 用 `coredumpctl` 的压缩/保留策略；
- 只映射必要段（部分系统支持）。

## 八、面试标准简答

### 1. CoreDump 是什么？

进程收到致命信号时，内核把进程的内存映射、寄存器、信号信息等写成文件，供事后调试。它是崩溃现场的完整快照。

### 2. 如何开启 CoreDump？

`ulimit -c unlimited` 打开资源限制，确认 `/proc/sys/kernel/core_pattern` 指向可写路径，确保进程 dumpable、磁盘空间足够；容器/服务还要单独配置。

### 3. core_pattern 以 | 开头是什么意思？

内核把 core 通过管道交给用户态程序处理（systemd-coredump、apport），由该程序决定存储位置和格式。`coredumpctl` 是 systemd 的访问接口。

### 4. 为什么 setuid 程序不生成 core？

安全考虑：core 可能包含敏感内存。setuid/setgid 进程默认不可 dump，由 `suid_dumpable` 策略控制。

## 九、极简口诀

**ulimit -c 开限制，core_pattern 定位置；**

**dumpable 要允许，磁盘空间要够；**

**管道交给 coredumpctl，build-id 对版本；**

**SIGKILL 不产 core，容器单独配。**

> （注：AI 辅助整理，建议结合本地 GCC / binutils 实测。）
