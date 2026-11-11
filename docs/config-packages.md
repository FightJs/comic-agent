# 配置包导入

状态（2026-11-05）：已实现JSON配置包的识别预览与应用，使用隔离钥匙串替身验证；未进行真实供应商联调。入口：项目库或项目内“模型设置”→“导入配置包”。配置包可一次填入四种用途，不要求用户逐项复制。

## 使用

1. 选择供应商或项目负责人提供的JSON配置包。
2. 核对预览中的用途、模型、服务地址和密钥动作。预览不保存配置，也不会发送模型请求。
3. 点击“应用这份配置”。仅更新列出的用途；未提供新密钥时保留该用途原有密钥。密钥保存到macOS钥匙串，不回退为明文。
4. 关闭设置后，正式配置保留；尚未应用的预览被丢弃。预览10分钟后失效，服务重启也失效。已应用不等于连接已验证。

示例（均为占位符，不是可用凭据或已验证模型）：

```json
{
  "format": "comic-config/v1",
  "name": "我的创作配置",
  "profiles": [
    {
      "purpose": "text",
      "url": "https://provider.example/v1",
      "model": "供应商实际模型标识",
      "api": "openai-completions",
      "secret": "在此放置真实API密钥"
    },
    {
      "purpose": "image",
      "url": "https://api.openai.com/v1",
      "model": "账户实际可用图像模型标识",
      "api": "openai-images",
      "secret": "图像用途的API密钥"
    }
  ]
}
```

用途：`text` 文本、`image` 图像、`vision` 看图、`parse` PDF解析。每种最多一次，一包最多四种；`url`、`model`在包内必填。`api`、`secret`可省略，空密钥表示保留旧密钥，不表示删除。

文本/看图协议可指定`openai-completions`、`openai-responses`、`anthropic-messages`，图像为`openai-images`，解析为`mineru`。协议配置不表示对应生产能力已完成：当前Pi讨论与图谱单次调用共用文本协议适配器；图谱不再把非Chat-Completions协议送到旧端点。图像与看图生产仍未真实接入，其他文本协议尚未真实供应商联调。

服务地址不得包含用户名、密码、查询参数或fragment。不要把密钥复制到名称、模型或地址字段。JSON之外的字段和脚本会明确拒绝，不执行上传代码。脚本与风格skill资源由后续独立安装与受控执行入口处理，尚未实现；这不是完整配置助手或完整Pi计划交付。

## 凭据与故障处理

- 配置文件由浏览器以受限原始JSON字节流上传（最多1MB），不用会为大文件生成临时磁盘文件的multipart解析。
- 原始包只在服务内存短暂保留，预览只返回密钥动作；应用后清除包对象，关闭丢弃或过期清理。不把包正文、密钥或哈希写入SQLite、会话、日志或下载物。用户原有JSON文件由用户保管。
- 手动配置和包导入共用写入锁与配置变更检查；预览之后配置改变（包括仅更新密钥）会返回冲突，要求重新预览。
- 多用途应用先读取旧密钥，写入失败会回滚已改密钥和配置。钥匙串回滚也失败时，明确列出需要核对的用途，不能宣称完整恢复。
- 同一预览令牌重复应用只返回原结果，不再次写入。服务重启或令牌失效后重新选择原文件。

接口：`POST /api/config-packages/preview`（原始JSON字节），`POST /api/config-packages/apply`和`/discard`（`{"token":"预览令牌"}`）。普通设置API沿用，新增可选协议字段`api`。

验证：`backend/tests/test_config_packages.py`、`frontend/src/ConfigImport.test.tsx`。独立真实页面审查见`docs/pi-config-ui-review.md`。测试和页面审核都使用临时数据/替身钥匙串，不能替代真实钥匙串授权或真实供应商联调。
