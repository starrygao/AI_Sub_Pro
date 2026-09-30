# 服务器 CLI 翻译服务

镜像包含 OMP CLI、Codex CLI 与 Claude Code。新安装默认使用 OMP，
模型 `openai-codex/gpt-6-astra`、推理强度 `medium`；已有 `config.json` 不会被入口程序覆盖。
在控制台「模型与处理」中选择主翻译服务、模型，也可独立选择润色服务。
要把现有主翻译和润色都切到 OMP，请分别选择 OMP 和上述模型、推理强度，不必改其他质量策略。
保存的设置会等当前任务完成并保存字幕后生效。

## 监控目录与网络代理

顶部「设置」中可直接编辑监控目录，任务页顶部也有快捷入口；无需滚动到任务列表底部。
「设置 → 网络代理」显示当前生效地址，并可修改、保存。代理服务器填写 HTTP/HTTPS
入口（例如 `http://127.0.0.1:7890`），管理页面单独填写（例如
`http://192.168.31.4:9097/ui/#/proxies`），可点击打开并管理节点。

这里的 `127.0.0.1` 指字幕服务所在服务器。首次使用继承容器环境变量；网页保存的新代理
在当前任务结束后应用，并保留到重启后。留空保存表示直连，原有 `NO_PROXY` 本地连接
绕过规则保留。管理页面地址仅用于浏览器跳转，修改它不会切换实际代理。

## OMP 安装、登录与持久化

Dockerfile 固定下载[官方 OMP v18.4.4 发布](https://github.com/can1357/oh-my-pi/releases/tag/v18.4.4)
的 Linux glibc 预编译文件，按目标架构选择，并在复制进最终镜像前验证 SHA-256：

| 架构 | 官方文件 | SHA-256 |
| --- | --- | --- |
| amd64 / x86_64 | `omp-linux-x64` | `24c830fceb0bd6884bf5bf2c7a2b7407bc23fafe655e924c695ef9be308e46f3` |
| arm64 | `omp-linux-arm64` | `602eefddc0fd87043f8f08d8628d72592e5802c003a05f203f1ecbc63a8fdd30` |

校验值来自[该版本 GitHub release 元数据](https://api.github.com/repos/can1357/oh-my-pi/releases/tags/v18.4.4)。
不使用浮动 latest、Mac 二进制或登录后的目录构建镜像；无须额外安装 Bun。
更换 OMP 版本时须一起核对官方文件名与 SHA-256。

升级前先创建独立的 OMP 状态目录，权限与 Compose 的 `AISUB_ROOT`、`AISUB_UID`、
`AISUB_GID` 保持一致。不要让 Docker 自动创建成 root 所有的空目录：

```sh
sudo install -d -m 700 -o "${AISUB_UID:-1000}" -g "${AISUB_GID:-1000}" \
  "${AISUB_ROOT:-/vol1/1000/docker/ai-sub-pro}/omp" \
  "${AISUB_ROOT:-/vol1/1000/docker/ai-sub-pro}/omp/agent"
docker compose -f deploy/docker/compose.yaml up -d --build ai-sub-pro
docker exec ai-sub-pro omp --version
docker exec ai-sub-pro sha256sum /opt/omp/omp
docker exec -it ai-sub-pro omp login openai-codex
```

版本输出应为 `omp/18.4.4`，哈希应与上表目标架构一致。登录必须使用服务运行用户，
不要添加 `--user root`。OMP 把登录保存在 `/omp/agent/agent.db`；
`PI_CODING_AGENT_DIR=/omp/agent` 和 `PI_CONFIG_DIR=/omp` 将认证及配置放在独立可写目录中，
由 `${AISUB_ROOT}/omp:/omp` 持久化。备份/重建时保留整个目录，不要把数据库或 token 放进源码、
镜像、环境示例或日志。

`/usr/local/bin/omp` 是仅为 OMP 设置 `HOME=/omp` 的启动脚本，真实二进制在
`/opt/omp/omp`。编译版的原生扩展仍会写入 `~/.omp/natives`，不能只设置
`PI_CONFIG_DIR`；这个局部 HOME 设置不影响 Codex、Claude 或媒体工具。

「同步模型列表」会调用 `omp models refresh --json`，同时刷新应用缓存和 OMP 上游目录，
保留已经选择的模型。同步列表不会升级 CLI；新模型若依赖较新的 OMP 版本，需要先升级
镜像或桌面外部 CLI。18.4.4 的可用目录包含 `openai-codex/gpt-6.1-sol`，实际可用性仍取决于账号权限。

在远程 NAS 上登录时，OpenAI Codex OAuth 需要浏览器的 `localhost:1455` 回调到服务器。
先在浏览器所在电脑另开终端执行 `ssh -N -L 1455:127.0.0.1:1455 <NAS用户>@<NAS地址>`，
保持隧道，再执行上面的容器登录命令，并在该电脑浏览器打开终端打印的授权链接。
这里依赖 Compose 的 host 网络；不要把回调端口公开到互联网。登录完成后可关闭隧道。

**Codex 已登录不代表 OMP 已登录。** 本部署不复制 `/codex/auth.json`，也不共享刷新 token。
OMP 18.4.3 官方 `auth-broker import` 接受 CLIProxyAPI 格式，不是 Codex 原生 `auth.json`；
切换请使用独立的 `omp login openai-codex`。认证由 OMP 自身保存和刷新。
参考[官方 provider 说明](https://github.com/can1357/oh-my-pi/blob/v18.4.3/docs/providers.md)
和[认证导入实现](https://github.com/can1357/oh-my-pi/blob/v18.4.3/packages/coding-agent/src/cli/auth-broker-cli.ts)。

## Claude 登录与持久化

升级前，在宿主机创建 Claude 目录并让容器用户可写。以下路径和 UID/GID 应与
Compose 的 `AISUB_ROOT`、`AISUB_UID`、`AISUB_GID` 一致：

```sh
sudo install -d -m 700 -o "${AISUB_UID:-1000}" -g "${AISUB_GID:-1000}" "${AISUB_ROOT:-/vol1/1000/docker/ai-sub-pro}/claude"
docker compose -f deploy/docker/compose.yaml up -d --build ai-sub-pro
docker exec -it ai-sub-pro claude auth login
```

在浏览器完成 Claude 登录，若终端提示输入授权码，将浏览器显示的授权码粘贴回终端。
不要添加 `docker exec --user root`：登录用户必须与服务运行用户一致。
控制台的「检查登录状态」仅检查安装及登录，不调用模型、不消耗翻译额度。

`CLAUDE_CONFIG_DIR=/claude` 与独立宿主机挂载目录保存 Claude 的配置和登录凭证，
重建容器时保留这个目录。不要把凭证复制到源码、镜像或日志中。
Codex 继续使用原有 `/codex` 目录，登录方式保持不变：

```sh
docker exec -it ai-sub-pro codex login --device-auth
```

主翻译与润色选择的服务都就绪后才启动新翻译。未登录或未安装时仍可检测视频并排队，
控制台会显示缺少哪个服务；登录后下一轮检查会自动恢复。
OMP 的登录检查针对当前所选模型；未安装、该模型没有可用认证或认证失效时，先完成对应服务登录再重试。
状态检查不进行翻译；模型目录及就绪结果不保证账号权限、剩余额度或下一次请求成功，首次实际翻译仍需验证。

Claude 存储与容器登录行为参考[官方认证文档](https://code.claude.com/docs/en/authentication)。
