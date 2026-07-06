# 案例：小爱音箱状态说明误播报

返回主文档：[通知类副作用保护方法论](../index.md)

## 现象

Agent 或自动化链路可能通过设备动作让小爱音箱播报一段状态说明，例如：

```text
水浸卫士误报了一次，不用担心。
```

如果这段话被重复执行，用户会听到多次无意义播报。即使只播一次，也不一定应该打扰用户。

## 根因判断

| 观察 | 判断 |
| --- | --- |
| 调用路径是 `call_action` | 这是设备动作，会真的影响外部设备 |
| 参数里包含状态说明文本 | 可以在后端出口识别 |
| 文案明确“误报/不用担心” | 不需要用户处理 |
| 设备动作可能被 Agent 重试 | 需要短窗口去重 |

结论：`call_action` 出口要先拦 status-only，再拦重复动作。

## 修复方式

后端在 `POST /api/miot/devices/{did}/control` 中对 `call_action` 增加保护：

| 条件 | 动作 |
| --- | --- |
| 参数文本是 status-only | 静默，不调用设备 |
| 同一 did + iid + params 短时间重复 | 静默，不调用设备 |
| 普通 `set_property` | 不走本规则 |
| 真正需要播报的告警 | 放行 |

API 返回保持成功语义：

```json
{
  "code": 0,
  "message": "Status-only device action suppressed",
  "data": {
    "suppressed": true,
    "reason": "status_only"
  }
}
```

## 验证方式

用同类 status-only 文案请求设备动作接口，预期：

- HTTP 返回 `code=0`
- `data.suppressed=true`
- `data.reason=status_only`
- 后端日志出现 `Suppressed status-only MIoT call_action`
- 小爱音箱不播报

同时要验证普通属性控制不受影响：

| 请求类型 | 预期 |
| --- | --- |
| `set_property` 开关灯 | 正常执行 |
| `set_properties` 批量设置 | 正常执行 |
| `call_action` 真告警播报 | 正常执行 |
| `call_action` status-only | 静默 |

## 可复用经验

| 经验 | 说明 |
| --- | --- |
| 设备动作比文字回复风险更高 | 它会真实打扰用户或改变设备状态 |
| 不要只看 API 名字 | `call_action` 可能是播报，也可能是执行指令 |
| 去重 key 要包含动作参数 | 同一设备不同话术不能互相误伤 |
| 静默要发生在调用设备前 | 不能先播报再记录“已拦截” |

相关方法论：[通知类副作用保护方法论](../index.md)
