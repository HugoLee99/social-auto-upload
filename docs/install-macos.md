# macOS 安装、打包与分发

本文分三段：**给 Apple 用户怎么装**、**你自己怎么产出安装包**、**签名/公证与排错**。

先说结论，三种交付形态的差别：

| 形态 | 谁生成 | 用户操作 | 能否零提示安装 | 适用场景 |
| --- | --- | --- | --- | --- |
| 引导安装包 `.zip`（`release/DaydreamDispatch-0.1.0-macOS-Installer.zip`） | 任意电脑（已生成） | 解压 → 双击 `安装白日梦.command` | 否，需右键「打开」一次 | 内测、朋友试用、今天就要给人装 |
| 原生 `DMG`（ad-hoc 签名） | 必须在 Mac 或 macOS CI | 打开 DMG → 拖进 Applications | 否，首次需右键「打开」或去隔离属性 | 有 Mac 可用、想给标准 `.app` 体验 |
| 原生 `DMG`（Developer ID + 公证） | Mac / CI + 付费开发者账号 | 打开 DMG → 拖进 Applications | 是 | 公开发布、正式售卖 |

> 为什么 Windows 上不能直接产出 DMG：PyInstaller 打出来的是**宿主平台**的可执行文件，Patchright 的 Chromium 也按 CPU 架构下载；`codesign` / `hdiutil` / `notarytool` 只在 macOS 上存在。所以「原生 DMG」这条路径必须在 Mac 或 GitHub Actions 的 `macos-*` runner 上跑。

---

## 零、直接下载已经发布好的安装包（0.1.1）

给普通用户最简单的方式：直接用 GitHub Release 里现成的 DMG，不需要他有 Xcode / Python / Node。

| 机型 | 下载链接 | 大小 | SHA256 |
| --- | --- | --- | --- |
| Apple Silicon（M1/M2/M3/M4） | [DaydreamDispatch-0.1.1-macOS-arm64.dmg](https://github.com/HugoLee99/social-auto-upload/releases/download/v0.1.1/DaydreamDispatch-0.1.1-macOS-arm64.dmg) | 334 MB | `281fec9471cab41375340e5ecf53266248850e2fe3c89f08de45b87b083a9bb3` |
| Intel 芯片（x86_64） | [DaydreamDispatch-0.1.1-macOS-x86_64.dmg](https://github.com/HugoLee99/social-auto-upload/releases/download/v0.1.1/DaydreamDispatch-0.1.1-macOS-x86_64.dmg) | 374 MB | `1e3bd7fe045108a7c0c5f09e7957142a596e9ab327243dd5fa46a9449ad49ac0` |

Release 页面：<https://github.com/HugoLee99/social-auto-upload/releases/tag/v0.1.1>

**安装三步**

1. 双击 DMG，把「白日梦内容分发助手.app」拖进 `Applications`（应用程序）文件夹。
2. **首次打开**：在 Finder 里右键这个 app → 选「打开」→ 弹窗里再点「打开」。
   也可以先执行一次去隔离：
   ```bash
   xattr -dr com.apple.quarantine "/Applications/白日梦内容分发助手.app"
   ```
3. 启动后会自动打开浏览器控制台 `http://127.0.0.1:5409`；账号、任务数据在
   `~/Library/Application Support/DaydreamDispatch`。

**说明**

- 包内已内嵌 Chromium（`chromium-1248`）与 ffmpeg，用户机器上不需要另装 Chrome。
- 最低系统：macOS 11.0；两个 DMG 都是在真实 macOS runner 上分别按 arm64 / x86_64 原生构建的。
- 当前是 **ad-hoc 签名、未公证**（项目还没有 Developer ID 证书），所以 Gatekeeper 一定会拦一次，
  这属于正常现象，不代表文件损坏；右键打开或去隔离即可。
- **不要用 v0.1.0**：那一版把 Chromium 放到了 `Contents/Resources`，而运行时是从
  `Contents/Frameworks`（`sys._MEIPASS`）找浏览器，会找不到。
- 卸载：删掉 app，再按需删 `~/Library/Application Support/DaydreamDispatch`。

---

## 一、给 Apple 用户：两种安装方式

### 方式 A：引导安装包（推荐给内测用户，无需你手上有 Mac）

发给对方 `DaydreamDispatch-0.1.0-macOS-Installer.zip`，让他按下面四步做：

1. **完整解压**到「下载」或桌面（不要在压缩包里直接双击）。
2. 右键点 `安装白日梦.command` → 选「打开」→ 弹窗里再点「打开」。
   - 若双击无反应，让他打开「终端」，执行：
     ```bash
     cd ~/Downloads/DaydreamDispatch-0.1.0-macOS-Installer
     bash "./安装白日梦.command"
     ```
3. 等 3–10 分钟（首次要联网下载 Python 3.12、依赖和 Chromium，约 300–400MB）。
4. 看到「安装完成，正在启动」后，浏览器会自动打开 `http://127.0.0.1:5409`。

安装脚本会做这些事（都在用户本机完成，不写系统目录、不需要管理员密码）：

```
~/Applications/白日梦内容分发助手.app        ← 生成的可双击应用
~/Library/Application Support/DaydreamDispatch/
   ├─ app/            程序本体（workbench_server.py 等）
   ├─ venv/           Python 3.12 环境（uv 创建）
   ├─ ms-playwright/  内置 Chromium
   ├─ cookies/        各平台登录态
   └─ .local/workbench/   草稿 / 上传素材 / 任务记录 / logs 日志
```

- Apple Silicon（M 系列）和 Intel 都是**本机原生**：Python 与 Chromium 在安装时按 `uname -m` 下载对应架构，不需要 Rosetta。
- 卸载：双击 `卸载白日梦.command`，先删应用，再询问是否清空 Cookie 与任务数据。

### 方式 B：原生 DMG

1. 双击 `.dmg` 打开磁盘映像。
2. 把「白日梦内容分发助手」拖到旁边的 `Applications` 快捷方式。
3. 首次双击应用前，先尝试**右键 → 打开**（未公证版本必须走这一步）。
4. 若系统仍拦截：打开「系统设置 → 隐私与安全性」，在页面下方点「仍要打开」；或在终端执行：
   ```bash
   xattr -dr com.apple.quarantine "/Applications/白日梦内容分发助手.app"
   ```
5. 首次启动同样会自动打开 `http://127.0.0.1:5409`。

用户数据位置与方式 A 相同（`~/Library/Application Support/DaydreamDispatch`），因为程序内部对两个平台的数据目录判断是固定写好的。

---

## 二、你自己怎么产出安装包

### 2.1 引导安装包（本机即可，已生成）

```powershell
# 在项目根目录（Windows / macOS 均可）
python packaging/macos/build_bootstrap.py --mode installer
```

产物：`release/DaydreamDispatch-<版本>-macOS-Installer.zip`。
想同时刷新「给 Mac 用的原生构建源码包」：`--mode all`（会覆盖 `release/DaydreamDispatch-0.1.0-macOS-build-source.zip`）。

### 2.2 原生 DMG：在 Mac 上一条命令

前置：macOS 11+、Xcode Command Line Tools（`xcode-select --install`）、Node.js 18+、网络可访问 npm / PyPI。

```bash
git clone <你的仓库> && cd social-auto-upload
chmod +x packaging/build-macos.sh
./packaging/build-macos.sh
```

产物：`release/DaydreamDispatch-0.1.0-macOS-arm64.dmg`（Intel 机器上会叫 `x86_64`）。
脚本做了这些事：建 `.venv-macos` → 装依赖 → 构建 Vue 前端 → 生成 `.icns` → 下载 **本机架构** 的 Chromium 并内嵌 → PyInstaller 出 `.app` → 签名 → 生成带 `Applications` 快捷方式的 DMG →（可选）公证。

已有前端产物、只想重打包：`./packaging/build-macos.sh --skip-frontend`。
不想内嵌 Chromium（体积小，但依赖用户自装 Chrome/Edge）：`SKIP_BROWSER=1 ./packaging/build-macos.sh`。

### 2.3 原生 DMG：在 GitHub Actions 上（无需 Mac）

仓库已带 `.github/workflows/build-macos.yml`，矩阵同时出 **arm64** 与 **x86_64** 两个 DMG：

- 手动触发：Actions → `Build macOS DMG` → Run workflow；
- 打标签自动构建并挂到 Release：`git tag v0.1.0 && git push origin v0.1.0`。

构建约 10–20 分钟，产物在 Actions 的 Artifacts 里，或在 Release 页面直接下载。

**签名/公证需要的 Secrets**（不配也能出包，只是 ad-hoc 签名）：

| Secret | 内容 |
| --- | --- |
| `MACOS_DEVELOPER_ID` | `Developer ID Application: 你的名称 (TEAMID)`，来自钥匙串里的证书全名 |
| `APPLE_ID` | Apple 开发者账号邮箱 |
| `APPLE_APP_PASSWORD` | App Store Connect 里生成的专用密码（不是登录密码） |
| `APPLE_TEAM_ID` | 开发者 Team ID（10 位） |

证书需要从本机钥匙串导出 `.p12` 并转成 base64 注入 runner，这一步按你们团队的密钥管理方式做；更简单的做法是在一台 Mac 上跑 `build-macos.sh` 并配好上述环境变量。

### 2.4 版本号与产物命名

版本号读 `pyproject.toml` 的 `project.version`，也可用 `DAYDREAM_VERSION=0.2.0` 覆盖。
产物命名：`DaydreamDispatch-<版本>-macOS-<架构>.dmg`。

---

## 三、签名、公证与 Gatekeeper

### 3.1 三种签名状态

| 状态 | 怎么产生 | 用户看到什么 |
| --- | --- | --- |
| 无签名 / 签名损坏 | 手动改过 `.app` 里的文件 | “已损坏，无法打开”，只能删掉重装 |
| ad-hoc（`codesign -s -`） | 本项目默认，未配证书时 | “无法验证开发者”，右键「打开」可过 |
| Developer ID + 公证 + 装订 | 配了证书与 Apple ID | 双击直接开，无拦截 |

- `build-macos.sh` 在未配置 `DEVELOPER_ID` 时会自动做 ad-hoc 签名——**这一步不能省**：Apple Silicon 上签名损坏的 `.app` 会被内核直接杀掉。
- 配了 `DEVELOPER_ID` 后脚本会由内向外重签（包含内嵌 Chromium 的 `*.framework` / 协助进程），再签 DMG。
- 配了 `APPLE_ID` + `APPLE_APP_PASSWORD` + `APPLE_TEAM_ID` 后自动 `notarytool submit --wait`、`stapler staple`、`spctl` 自检。

单独公证一个已构建好的 DMG：

```bash
xcrun notarytool submit release/DaydreamDispatch-0.1.0-macOS-arm64.dmg \
  --apple-id "me@example.com" --password "abcd-abcd-abcd-abcd" --team-id "TEAMID" --wait
xcrun stapler staple release/DaydreamDispatch-0.1.0-macOS-arm64.dmg
xcrun stapler validate release/DaydreamDispatch-0.1.0-macOS-arm64.dmg
```

查看某个用户机器上的拦截原因：

```bash
xattr -l "/Applications/白日梦内容分发助手.app"       # 看 com.apple.quarantine
codesign -dv --verbose=4 "/Applications/白日梦内容分发助手.app"
spctl --assess --type execute -vv "/Applications/白日梦内容分发助手.app"
```

### 3.2 为什么苹果用户会更在意这些

macOS 会把「从网络下载」的文件打上 `com.apple.quarantine` 标记，首次运行时 Gatekeeper 校验签名与公证记录。内测阶段用 ad-hoc 签名 + 右键打开是常规做法；一旦对外公开发布，建议配 Developer ID 与公证，否则用户会频繁遇到拦截、口碑也会变差。

---

## 四、上线前必须在真 Mac 上过一遍的验收清单

Windows 上只能验证脚本语法、压缩包结构与代码路径，**功能必须在 Mac 上跑一次**：

1. `安装白日梦.command` 双击（未右键）是否被拦截，右键「打开」能否继续。
2. 安装完成后 `~/Applications` 里出现应用，图标正常。
3. 双击应用 → 浏览器自动打开 `http://127.0.0.1:5409`，控制台可交互。
4. 添加一个账号 → 点登录 → Patchright Chromium 能启动（首次可能弹「自动化/辅助功能」授权）。
5. 发一条 10 秒测试视频到小红书或抖音，成功回执。
6. 应用运行中再双击一次：不应起第二个服务，而是直接打开页面。
7. 关闭应用（活动监视器结束 python）→ 重新双击能正常恢复。
8. Intel Mac 上重复第 2–5 步；再验证 `x86_64` 的 DMG。
9. `卸载白日梦.command` 能删应用，并正确询问是否清 Cookie。
10. 若已配证书：`spctl --assess` 通过、DMG 双击无拦截。

---

## 五、已知限制与排错

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| “已损坏，无法打开” | 签名失效（手动改过包内文件 / 压缩方式破坏签名） | 重装原始 DMG；或 `xattr -dr com.apple.quarantine` 后重试；正式分发请公证 |
| “无法验证开发者” | ad-hoc 签名，未公证 | 右键 → 打开；或系统设置 → 隐私与安全性 → 仍要打开 |
| 双击 `.command` 无反应 | 解压后丢了执行权限 | 终端执行 `bash "./安装白日梦.command"` |
| 端口 5409 被占用 | 已有实例或别的程序 | 用 `SAU_PORT=5410` 启动；或先退出旧实例 |
| 发布时报浏览器/驱动错误 | 没装内置 Chromium，也没装 Chrome | 补装 Chromium（命令见 `使用说明.txt`），或安装 Google Chrome |
| 文章渲染失败 | 文章主题渲染依赖 Node.js 22+ | 安装 Node.js 后再发文章；纯视频发布不需要 |
| B 站登录/发布卡住 | 首次会从 GitHub 下载 `biliup` | 保证能访问 GitHub Release；失败重试登录 |
| Apple Silicon 上启动闪退 | 拿了 x86_64 的旧包 / Rosetta 缺失 | 换 `arm64` 包；引导安装包不受影响（本机原生下载） |
| 上传大视频很慢/失败 | 网络与平台限速 | 与打包无关，先本地确认视频可正常上传 |

其他注意：

- 程序只监听 `127.0.0.1`，不会暴露到局域网；不要在路由器上做端口转发。
- `cookies/` 等同账号凭证，别随日志、截图一起外发。
- 首次运行 macOS 可能要求「辅助功能」「自动化」权限（程序要代替你操作浏览器），按提示允许即可；拒绝后登录/发布会失败。
