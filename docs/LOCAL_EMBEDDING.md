# 本地中文语义向量检索

程序已有的 `local` 是 256 维字词哈希。此服务使用预训练中文模型，通过已有的 `api` 后端接入，保持 SQLite 混合检索、作用域、来源和删除规则。

模型为 [BAAI/bge-small-zh-v1.5](https://huggingface.co/BAAI/bge-small-zh-v1.5)，FastEmbed 的 [支持列表](https://qdrant.github.io/fastembed/examples/Supported_Models/)提供其 512 维 ONNX 版本。运行于本机 CPU；首次需下载公开模型，日常推理通过本机 127.0.0.1，不需要向量 API Key。聊天模型仍使用独立设置的提供方。

## 安装和启动

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[embedding]"
.\.venv\Scripts\python.exe -m companion_agent.embedding_server --port 8080
```

模型默认缓存于 `.agent-data/embeddings`，不放入版本控制。服务只绑定本机回环地址；`GET /health` 返回已加载模型、维数和调用计数，`POST /v1/embeddings` 接受字符串或最多 16 条字符串。接口不记录输入正文，不复用聊天 Key。

Windows 需要兼容的 Microsoft C++ 运行库，参见 [微软说明](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)。本机旧的系统 `msvcp140.dll` 导致 ONNX 导入失败，本次使用现有工具环境中微软签名有效的 14.51.36247.0 DLL，复制到项目专用目录，未替换系统 DLL。来源文件哈希和签名检查回执保存在 `.agent-data/embeddings/runtime-manifest.json`。

本机启动命令：

```powershell
$env:HF_HUB_DISABLE_XET = "1"
.\.venv\Scripts\python.exe -m companion_agent.embedding_server --port 8080 --runtime-dir .agent-data/embeddings/runtime
```

`--runtime-dir` 是可选的本机运行库目录，只用于 Windows。其他电脑应安装合适的运行库或提供自己可信的目录。不要从无关下载站获取 DLL。该服务是独立进程；程序或电脑重启后，如果服务已停止，需要重新运行上述命令。本次不创建系统开机任务。

本机首次通过 FastEmbed 提供的 Google Storage 备用源下载模型，验证权重 SHA-256 为 `1294ea4b6331115a353d81f96b85e8c8d7fdcc284453d5b2fab5b016230aad38`，与 Hugging Face 对应版本的 LFS 元数据相同。缓存完整后可设置 `$env:HF_HUB_OFFLINE = "1"` 再启动，避免依赖联网检查。

## 应用设置

将“记忆提取/检索”里的向量后端设为 API，填入：

- 地址：`http://127.0.0.1:8080/v1`
- 模型：`BAAI/bge-small-zh-v1.5`
- Key：留空，本机服务无需 Key

保存后由应用按已有逻辑为当前作用域的 active 记忆建立或更新向量，查询同时使用中文 FTS 和语义向量。更换模型名称会改变向量空间标识，避免与以前字词哈希或其他模型混用。只有配置为 API 或页面显示 ready 不足以证明向量参与了本轮；实际测试应核对非空查询向量、检索命中及最终送给模型的证据。

当前传输对查询与记忆正文均使用不加指令的编码；BGE v1.5 模型说明允许这种用法。输入由模型截断为最多 512 token，适合短记忆卡；超长聊天不能据此宣称完整覆盖。向量能改善语义匹配，不会自动修复提取失败、未采用的候选、版本状态或错误的证据使用计划。
