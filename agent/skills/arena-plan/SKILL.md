---

## name: arena-plan
description: >-
  基于 Arena Swim 官方课表库生成结构化 SwimTrainingPlan。出计划时必须加载本 Skill：
  先按档案与诉求在 6 大主题中选定唯一模板，再结合历史摘要卡调整，禁止从零编课。

# Arena 训练计划 Skill

出计划 Agent **必须**先读本文件，再读 `[data-access.md](data-access.md)` 与选中的 `templates/.../*.yaml`。

## 资源索引


| 资源         | 路径                                             | 何时读             |
| ---------- | ---------------------------------------------- | --------------- |
| 本流程 + 主题分类 | `SKILL.md`                                     | **每次必读**        |
| 档案 / 摘要卡   | `[data-access.md](data-access.md)`             | 读 Data pack、调课前 |
| 官方课表正文     | `[templates/](templates/)`（按主题分子目录）            | 选定后只读 **1** 份   |
| 机器索引       | `[templates/index.json](templates/index.json)` | 选型时查路径          |


模板正文来自 Arena 公开 API：

- 列表：`GET https://www.arenaswim.com/api/training`（英文化标题 / Goal / Level）
- 详情：`GET https://www.arenaswim.com/api/training/{ref}`（`sets` 组距原文）

已映射为本项目 `SwimTrainingPlan.sections` 合法字段（`warmup|main|cooldown` 等）。标题与 `note` 已全部本地化为**简体中文**；距离/次数来自官方 API，**未从 API 拿到的计划不得编造。**

---



## 六大主题分类（Arena「达成你的目标」）

与官网 Goal 一一对应（中文界面 / 英文 API）：


| 主题（中）  | Arena Goal（英）           | `goal_bucket` | 目录                                                                       | 计划数    |
| ------ | ----------------------- | ------------- | ------------------------------------------------------------------------ | ------ |
| 学习这项技术 | Learn the technique     | `learn`       | `[templates/learn-the-technique/](templates/learn-the-technique/)`       | **5**  |
| 提高你的技巧 | Improve your technique  | `technique`   | `[templates/improve-your-technique/](templates/improve-your-technique/)` | **13** |
| 速度     | Speed                   | `speed`       | `[templates/speed/](templates/speed/)`                                   | **9**  |
| 耐力     | Endurance               | `endurance`   | `[templates/endurance/](templates/endurance/)`                           | **20** |
| 塑形燃脂   | Tone Up & Burn Calories | `tone`        | `[templates/tone-up-burn-calories/](templates/tone-up-burn-calories/)`   | **10** |
| 健康福利   | Well-being              | `wellbeing`   | `[templates/well-being/](templates/well-being/)`                         | **3**  |


合计 **60** 份（与 API 列表一致）。每份文件名：`{arena_ref}-{slug}.yaml`，内含 `template_id: arena-{ref}`。

### 主题内计划清单（中文标题）



#### 1. 学习这项技术（5）· `templates/learn-the-technique/`


| ref | 标题         | level | 时长  |
| --- | ---------- | ----- | --- |
| 189 | 自由泳…但别太自由！ | easy  | 45  |
| 190 | 仰泳练习！      | easy  | 45  |
| 210 | 提升仰泳技术！    | easy  | 30  |
| 241 | 自由泳-改善头部位置 | easy  | 45  |
| 243 | 自由泳-提升腿部打水 | easy  | 30  |




#### 2. 提高你的技巧（13）· `templates/improve-your-technique/`


| ref | 标题                    | level  | 时长  |
| --- | --------------------- | ------ | --- |
| 186 | 混合泳训练 - 蛙泳            | hard   | 75  |
| 208 | 混合泳训练 - 蝶泳            | hard   | 75  |
| 209 | 混合泳训练 - 仰泳            | hard   | 75  |
| 220 | 技术优化 - 水中半小时训练        | easy   | 30  |
| 227 | 蛙泳：初学者与业余爱好者训练计划      | medium | 40  |
| 229 | 蝶泳：初学者与业余爱好者训练计划      | medium | 30  |
| 238 | 如何使用脚蹼和呼吸管训练          | medium | 45  |
| 242 | 自由泳-改善肩部转动            | medium | 45  |
| 244 | 自由泳 - 改善呼吸            | medium | 45  |
| 277 | 训练3 - 技术              | medium | 110 |
| 294 | 提升推进效率（公开水域）- 恢复周，训练1 | easy   | 40  |
| 295 | 提升推进效率（公开水域）- 恢复周，训练2 | easy   | 40  |
| 494 | 单臂自由泳练习               | medium | 30  |




#### 3. 速度（9）· `templates/speed/`


| ref | 标题                    | level  | 时长  |
| --- | --------------------- | ------ | --- |
| 181 | 无氧力量                  | medium | 30  |
| 217 | 冲刺型运动员——泳池训练          | hard   | 75  |
| 219 | 速度训练 - 优化你的游泳表现       | easy   | 30  |
| 245 | 自由泳 - 改进水下打腿          | hard   | 45  |
| 261 | 用混合泳组合开启训练 - 3        | hard   | 45  |
| 276 | 训练2 - 速度              | medium | 110 |
| 291 | 提升推进效率（公开水域）- 速度周训练1  | easy   | 40  |
| 292 | 提升推进效率（公开水域）- 速度周训练2  | easy   | 60  |
| 293 | 提升推进效率（公开水域）- 速度周，训练3 | medium | 60  |




#### 4. 耐力（20）· `templates/endurance/`


| ref | 标题                      | level  | 时长  |
| --- | ----------------------- | ------ | --- |
| 177 | 是时候训练腿部了！               | hard   | 75  |
| 179 | 有氧力量                    | hard   | 75  |
| 180 | 无氧力量                    | hard   | 30  |
| 218 | 耐力训练 - 优化你的游泳表现！半小时水中训练 | easy   | 30  |
| 257 | 用混合泳组合开启训练              | hard   | 60  |
| 259 | 以混合泳组合练习开启你的训练——2       | hard   | 60  |
| 272 | 长距离游泳训练 - 1             | medium | 90  |
| 275 | 训练1 - 有氧                | medium | 110 |
| 288 | 提升推进效率（公开水域）- 增强周，训练1   | easy   | 60  |
| 289 | 提升推进效率（公开水域）- 增量周，训练2   | easy   | 50  |
| 290 | 提升推进效率（公开水域）- 增强周，训练3   | easy   | 40  |
| 296 | 提升推进效率（公开水域）- 恢复周，训练3   | medium | 50  |
| 431 | 10×100测试                | medium | 75  |
| 455 | 时间不多也高效 - 有氧功率训练        | medium | 75  |
| 456 | 时间不多也高效 - 有氧训练          | medium | 50  |
| 457 | 时间不多也高效 - 乳酸训练          | medium | 60  |
| 482 | 提升公开水域耐力 #1             | hard   | 90  |
| 483 | 提升公开水域耐力 #2             | hard   | 75  |
| 484 | 提升公开水域耐力 #3             | hard   | 90  |
| 496 | 保持前进                    | medium | 45  |




#### 5. 塑形燃脂（10）· `templates/tone-up-burn-calories/`


| ref | 标题                | level  | 时长  |
| --- | ----------------- | ------ | --- |
| 175 | 消耗卡路里             | medium | 60  |
| 191 | 为夏天恢复体形！#1        | medium | 60  |
| 192 | 为夏天恢复体能！#2        | medium | 90  |
| 193 | 为夏天恢复体能！#3        | medium | 105 |
| 194 | 为夏天恢复体能！#4        | medium | 105 |
| 201 | 时间不多？别担心——第一部分    | medium | 50  |
| 202 | 时间不多？训练也高效！- 第二部分 | medium | 50  |
| 203 | 时间不多？训练也没关系——第三部分 | medium | 50  |
| 204 | 时间不多？训练方案4        | medium | 60  |
| 434 | 沙滩训练！             | medium | 45  |




#### 6. 健康福利（3）· `templates/well-being/`


| ref | 标题        | level  | 时长  |
| --- | --------- | ------ | --- |
| 199 | 重新开始训练    | medium | 90  |
| 211 | 水中身心放松    | easy   | 45  |
| 439 | 游泳练出结实臀部！ | easy   | 30  |


路径与 volume 以 `[templates/index.json](templates/index.json)` 为准。

---



## 分析流程（不可颠倒）

```text
1. 按 data-access 读 Data pack（profile / user_request / summary_cards）
2. 映射 goal_bucket（下表）× level（easy/medium/hard）
3. 在对应主题目录中选唯一 template_id（优先 duration/volume 贴近上场距离）
4. 打开该 YAML，以 sections 为骨架
5. 用摘要卡调整距离 / repeat / rest_s / note；不改课型主题
6. 按 pool_length_m 对齐距离
7. 输出 SwimTrainingPlan.sections
```



### goal_bucket 触发词


| bucket      | 触发词                 |
| ----------- | ------------------- |
| `learn`     | 学游泳、入门、不会、学习技术      |
| `technique` | 技术、分解、效率、SWOLF、提高技巧 |
| `endurance` | 有氧、耐力、匀速、长距离        |
| `speed`     | 速度、冲刺、配速            |
| `tone`      | 减脂、塑形、燃脂            |
| `wellbeing` | 健康、放松、恢复、福利         |


`user_request` > 档案 `goal`；不明默认 `endurance`。

### level


| level    | 依据                                 |
| -------- | ---------------------------------- |
| `easy`   | 近场均距 <800m，或 `learn`，或样本不足 / 需恢复减量 |
| `hard`   | 近场均距 ≥2000m 且无疲劳警告                 |
| `medium` | 其余                                 |


摘要要求恢复/减量 → 优先同主题 shorter，或 `wellbeing`。

### 调参与输出

- 总距离贴近上场 × [0.6, 1.3]，且落在模板 `volume_band_m`
- 保持多组 + rest；禁止无 rest 的超长单块 main（≥800m 且 repeat 空/1）
- 陆上热身（Arena dryland）不进 sections，见模板可选字段 `dryland_note`
- 枚举合法：`stroke` / `drill_type` / `equipment`；至少 1×warmup、1×main、1×cooldown
- 种子 `equipment`（器材）有值必须保留并输出，供墨水屏显示「器材」行；勿一律 null

