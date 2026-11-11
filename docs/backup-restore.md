# 停服备份与隔离恢复核对

2026-11-06。现有 `backend/store.py` 使用 SQLite WAL 和不可变文件，没有项目备份 API。沿用 README 的**停止服务后复制整个 data 目录**；图片 ZIP 只含采用图片，不是项目备份。本页新增的是手工流程及临时合成演练，不提供在线一致性快照、自动恢复生产或钥匙串迁移。

## 先做无真实数据演练

在项目根目录执行：

```sh
PATH=/Users/xiaochao/.nvm/versions/node/v22.23.1/bin:$PATH .venv/bin/python scripts/verify_backup_restore.py
PATH=/Users/xiaochao/.nvm/versions/node/v22.23.1/bin:$PATH .venv/bin/python -m pytest backend/tests/test_backup_restore.py -q
```

需要已安装的 Python 依赖、`agent-runtime/node_modules` 及 Node ≥22.19。脚本不接受路径或参数；只创建临时合成目录，退出清理，不读取工作区 `data/`、用户钥匙串、真实原著或真实会话，也不启动后端、Pi server 或供应商请求。Node 只调用现有 `RunCheckpoint` 和锁定 Pi SDK 的会话文件 API。

演练依次验证：

1. 使用真实 Store 保存合成原件、两个版本和 import 来源；退出全部数据库连接及 Node 写入进程。
2. 对整棵目录建立相对路径 SHA256 清单，复制备份，再复制到独立恢复目录。原件、SQLite、Pi 会话、检查点及合成锁证据逐文件一致；遇到符号链接拒绝，不跟随外部文件。
3. 恢复副本 `PRAGMA integrity_check` 为 `ok`，两个版本、内容和来源准确，原件 bytes/hash 相符。
4. 真实 Pi SDK 能从恢复后的相对会话路径读取检查点指定 leaf；干净 paused 账本可以形成原分支的续接计划，但不 claim child、不派发；同 run 再 start 被 `run_recorded` 拒绝；有一笔未返回模型登记的账本续接被 `checkpoint_unresolved` 拒绝。未知计数保留为 1。
5. 读取与边界核对后，恢复目录及源目录的文件 SHA256 仍一致。脚本输出布尔/计数证据，不输出文件路径、会话正文、配置或密钥。

本次专项结果：3 passed。命令行演练输出 `sqlite_integrity: "ok"`、`versions_preserved: 2`、三个 Pi 边界字段为 true、`provider_calls: 0`。合成库已关闭且 WAL 不存在才使用 `immutable=1` 读取以保持哈希；真实备份若保留 WAL，不可照搬该选项忽略 WAL。

## 实际备份：先停服，再复制

1. 先保存编辑。浏览器未保存草稿不在 data 中；需要的草稿先明确保存或另行留存。
2. 在原服务终端按 Ctrl+C，等待后端及其 Pi 子进程退出。若有未知供应商结果，记录原任务/run ID；停服不是撤单、退款或证明请求未发送。不要为了备份点击重试。
3. 确认没有其他窗口、服务或脚本继续写入同一 data。仅“页面已关闭”不足以证明停止。先确定本次实际 data 根目录：默认项目根 `data/`；使用 `COMIC_DATA_DIR` 或 `create_app(data_dir)` 时以真实配置为准。
4. 选择受控备份位置，父目录权限仅当前用户可访问。复制**整个** data，包含 SQLite 的 WAL/SHM（如果存在）、files、agent 的所有会话/检查点/恢复日记与其他文件，不按白名单挑选。不要在复制中启动服务。下面命令是供用户在停服后执行的示例，不由演练脚本自动执行。

将两处占位路径改成绝对路径；备份目标必须尚不存在。项目根目录执行：

```sh
SOURCE_DATA="/实际数据根目录/data" BACKUP_DIR="/受控备份位置/backup-2026-11-06" .venv/bin/python - <<'PY'
import json, os, shutil
from pathlib import Path
from scripts.verify_backup_restore import inventory, verify_copy
source=Path(os.environ['SOURCE_DATA']).resolve()
target=Path(os.environ['BACKUP_DIR']).resolve()
if not (source/'workbench.sqlite').is_file():raise SystemExit('源数据库不存在')
if target==source or source in target.parents:raise SystemExit('备份必须位于源数据目录之外')
target.mkdir(mode=0o700,parents=False,exist_ok=False)
expected=inventory(source)
shutil.copytree(source,target/'data')
verify_copy(expected,target/'data')
manifest=target/'sha256.json'
manifest.write_text(json.dumps(expected,sort_keys=True),encoding='utf-8')
manifest.chmod(0o600)
print('备份复制及逐文件SHA256核对通过；未启动服务')
PY
```

清单含相对路径与哈希，按私有项目资料保护，不上传公开仓库。备份包含原著、聊天、生产请求和配置元数据；即使没有配置密钥也属于敏感项目资料。备份位置的父目录需预先存在；目标已存在会拒绝覆盖。复制或校验失败时保留失败证据并重做一个新目标，不把部分目录当作可用备份。

## 隔离恢复：不覆盖原库、不启动生产

先准备与备份时相同的应用代码版本、资源及锁定依赖，记录对应 Git commit/发布版本。data 不包含应用代码、Python/Node 依赖和浏览器草稿；外部自行管理的资料也不因目录复制自动纳入。不要直接用未知新版本启动备份并执行迁移。

先检查备份清单，再复制到新的恢复根目录，恢复目标必须不存在；保持原备份不动：

```sh
BACKUP_DIR="/受控备份位置/backup-2026-11-06" RESTORE_DATA="/独立恢复位置/restored-data" .venv/bin/python - <<'PY'
import json, os, shutil, sqlite3
from pathlib import Path
from scripts.verify_backup_restore import verify_copy
backup=Path(os.environ['BACKUP_DIR']).resolve()
restored=Path(os.environ['RESTORE_DATA']).resolve()
if restored==backup or backup in restored.parents:raise SystemExit('恢复位置必须独立于备份')
expected=json.loads((backup/'sha256.json').read_text(encoding='utf-8'))
verify_copy(expected,backup/'data')
shutil.copytree(backup/'data',restored)
verify_copy(expected,restored)
# 只读连接可能建立WAL/SHM辅助文件；只操作恢复工作副本，不改备份。
with sqlite3.connect((restored/'workbench.sqlite').as_uri()+'?mode=ro',uri=True) as db:
    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('数据库完整性核对未通过')
    counts={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('projects','records','versions','files')}
print('隔离副本文件校验与SQLite完整性通过；记录数量：',counts)
print('尚未启动服务、恢复会话或提交任何模型调用')
PY
```

实际恢复还需人工核对原件、采用/审核版本、关键项目与固定运行记录是否完整。不要用 `Store(restored)` 代替只读校验：Store 初始化及各业务注册可能执行迁移、将旧 running 标为 interrupted/unknown，这属于启动后的状态整理，不是原件哈希一致的只读证明。需要页面查看时，另复制一份恢复工作目录、明确指定独立 `COMIC_DATA_DIR` 和端口后再启动；避免同时打开旧服务。此页不自动启动或自动点击任何继续、生成、修复、恢复结果按钮。

## 凭据、会话和运行锁的边界

- macOS 钥匙串不在 data 中。本流程不读取、导出或迁移密钥；在新环境由用户重新配置所需用途的密钥。恢复配置元数据不代表钥匙串已恢复或供应商连接已验证。
- 保留原项目、会话、run、任务/调用 ID、精确分支、SQLite 宿主回执及相对会话文件关系。不要只拷 session JSONL，也不要只拷 SQLite；恢复日记/快照和父子续接关系必须一起保留。不得把旧编号换新编号当作恢复。
- 所有已有运行锁/登记证据照原件保留。复制锁不迁移活进程的占用权，不授予新进程重发权限；不要删除 lock、检查点或回执来“解锁”。检查点显示 running/未知、未决工具或未返回模型时，只读核对原回执，不能自动续接。
- 干净 paused 且保存准确 SDK 分支只是续接的必要条件。恢复后仍需原输入/版本/权限/公开供应商配置校验与用户新一段明确授权；恢复目录本身不提供该授权。
- 仅工具结果恢复仍按现有精确宿主回执/参数 hash/结果 hash/最后工具组/分支守卫执行；本次演练没有调用该写入恢复流程。缺账本或历史不完整时不能补造通过。

## 证据限制

这是本机临时合成数据、真实 Store/锁定 Pi SDK 文件 API 的停服复制演练。没有做真实用户数据迁移、断电/磁盘损坏、备份加密/异地灾备、供应商结果对账、密钥迁移或付费模型请求。SHA256 清单证明复制前后对应文件一致，不是恶意篡改防护签名；SQLite integrity 不证明原著、视觉或摘要语义质量。全应用恢复后的页面、采用/审核及生产流程须另行验收；不以本页结果宣称全部系统恢复完成。
