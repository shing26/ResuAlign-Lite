# ADR-0035: LLM API Key 静态加密（secret_box）

- 状态：Accepted
- 日期：2026-09-11
- 关联：外部模型分析报告核查（"本地密钥明文存储风险"确认为真问题）；ADR-0013（租户与工作区存储）

## 背景与问题

LLM API Key 以明文存放在本地 SQLite：`llm_nodes.api_key` 列与
`user_settings.llm_json` 内嵌字段。这些 db 是普通文件，会被备份脚本、
云同步盘、误操作分享复制——**db 文件单独泄露即等于 LLM 账户凭据泄露**
（可产生真实账单）。读取侧已有掩码（路由层）与日志脱敏，但静态存储无保护。

## 决策

1. 新增 `resualign/secret_box.py`：基于 `cryptography` 的 Fernet 对称加密。
   密钥文件为数据目录下的 `secret.key`（首次使用自动生成，0600），可用
   `RESUALIGN_SECRET_KEY_FILE` 覆盖（容器挂载/测试隔离）。
2. 存储格式 `enc:v1:<fernet-token>`。**无前缀的值按遗留明文原样透传**：
   存量行读路径零破坏，下次保存时自然升级为密文（无启动迁移副作用）。
3. 加解密收敛在 store 层边界（`llm_nodes` 写入两处 + `_row_to_dict` 读；
   `settings_store` 的 `_llm_for_storage` 写 + `_parse_llm_json` 读），
   调用方（路由、pipeline、掩码逻辑）零改动。
4. `cryptography>=42.0.0` 进入正式依赖。

## 后果与诚实局限

- **防住**：db 文件单独泄露（误发 .db、云盘只同步了 jobs.db、备份裸拷 db）。
- **防不住**：整盘/整个数据目录被入侵（密钥文件与 db 同机）——这是本地
  单机应用的诚实边界；OS 级凭据保险箱（keyring/DPAPI）在 Docker/无头
  Linux 场景不可用，故不采用。
- **平台权限差异**：`0o600` 创建模式在 Windows 上被忽略（NTFS ACL 生效），
  仅 POSIX 系统获得严格权限；文档化以免误判为已收紧。
- 密钥文件丢失或被替换时，已存 Key **永久不可解密**：decrypt 抛出带恢复
  指引的 RuntimeError（而不是静默返回空值伪装正常）；用户需恢复密钥文件
  或在设置页重新录入 Key。
- 遗留明文行在"只读不写"的使用路径下不会自动升级；可接受（写路径已全部
  收口，实际系统中 key 迟早会随一次编辑被重写）。

## 备选方案（未采纳）

- **OS keyring**：凭据安全边界最好，但 Docker / 无头 Linux / 多后端差异
  使部署与测试复杂度不成比例。
- **仅 DPAPI（Windows）**：平台绑定，破坏跨平台与容器部署。
- **不加密，只靠文件权限**：权限对"文件被复制走"这一主泄露路径无效。
