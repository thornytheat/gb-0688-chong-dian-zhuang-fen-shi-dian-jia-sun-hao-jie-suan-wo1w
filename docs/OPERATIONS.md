# 运行维护

主服务端口与Compose保持一致。数据保存在records命名卷，应用代码不需要写入权限。

```sh
docker compose logs --tail=80 app
docker compose restart app
docker compose exec -T app pytest -q
docker compose down --remove-orphans
```

健康检查GET /health。失败输入返回原因码，结构性错误422，过大文件413，陈旧复核409。
文件内容最大4MB。批次先计算再原子保存，失败不留半条记录。证据CSV按原始行号定位。

## 补读派生

- 派生版本存于同一 SQLite：`derived`（版本与进度）、`current`（站点唯一当前账）、`current_history`（切换与恢复依据）。原批次 `runs` 只读。
- 中断后续跑：重新提交同一份补读即可，已确认时段不会重算，也不会新建版本。核对未通过时版本为 `核对失败`，修正补读内容后可重新生成。
- 切换失败返回 409 `WRITE`，当前账自动回到旧版账单并写入切换历史；必要时 `POST /api/m8/<id>/restore` 手动恢复。核对失败的版本不能切换（422 `STATE`）。
- 页面 `/m/8` 与凭证 `/api/m8/<id>/evidence.csv` 同时呈现当前账、原批次与补读依据；凭证包含合并读数、重叠隔离、补读隔离与当前账指针。
- 本模块不改电价政策，也不产生真实收费。
