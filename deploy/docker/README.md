# 服务器 CLI 翻译服务

镜像包含 Codex CLI 与 Claude Code。现有服务器升级后保留当前翻译设置；新安装仍默认使用 Codex。
在控制台「模型与处理」中选择主翻译服务、模型，也可独立选择润色服务。
保存的设置会等当前任务完成并保存字幕后生效。

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
模型目录中的选项不保证账号权限或配额，首次实际翻译仍需验证。

Claude 存储与容器登录行为参考[官方认证文档](https://code.claude.com/docs/en/authentication)。
