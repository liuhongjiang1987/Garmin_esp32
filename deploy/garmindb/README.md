# NAS 上的 GarminDB

把 Garmin Connect 的数据下载到 NAS 本地目录 `home/HealthData`。容器不监听端口。GarminDB 自己要写入数据库，所以这个目录不能设成只读。后面的教练程序再单独用只读方式打开这些库。

账号是佳明中国（网页是 `connect.garmin.cn`）时，把配置里的 `garmin.domain` 改成 `garmin.cn`。国际区账号保持 `garmin.com`。

## 1. 放到 NAS

把本目录拷到 NAS，例如 `/volume1/docker/garmindb`。用 SSH 进入该目录。群晖、威联通都先打开 SSH，比容器图形界面更容易输入验证码。

```bash
mkdir -p home/.GarminDb
cp GarminConnectConfig.json.example home/.GarminDb/GarminConnectConfig.json
```

编辑 `home/.GarminDb/GarminConnectConfig.json`：

- 填入佳明账号和密码。这个文件只留在 NAS 上。
- 四个 `*_start_date` 改成你开始使用佳明的日期，格式是 `MM/DD/YYYY`。
- 活动超过 1000 条时，调大 `download_all_activities`。

## 2. 第一次全量同步

NAS 需要能访问外网，以便拉取 `python:3.12-slim` 和 Garmin Connect。

```bash
docker compose build
docker compose run --rm -it garmindb --all --download --import --analyze
```

终端如果停下并要求验证码，输入手机或邮箱里的那一位数后回车。登录令牌会写进 `home/`，下次不用再输。全量同步可能要几十分钟，结束前不要关这个会话。

完成后应能看到：

```text
home/HealthData/DBs/garmin.db
home/HealthData/DBs/garmin_activities.db
home/HealthData/DBs/garmin_monitoring.db
home/HealthData/DBs/garmin_summary.db
```

同时还有 `FitFiles/`、`Monitoring/` 等原始文件。这些原始文件要留着，以后数据库结构升级时可以不重新从佳明下载。

## 3. 每天增量

在 NAS 的计划任务里每天跑一次，不要加 `-it`。只同步活动，不下载监测、睡眠、体重和静息心率。

`--latest` 下载仍然只向佳明要最近若干条。导入会跳过已入库的活动。导入成功后，同一条命令会接着计算还没写进 `swim_evidence.db` 的游泳指标。没有新活动时这一步只做跳过。

计划任务不用改命令。更新镜像后，下一次定时运行就会带上指标计算。

```bash
cd ~/garmindb
sudo docker-compose run --rm garmindb --activities --download --import --latest
```

任务失败时先看这次命令的输出。常见原因是佳明登录过期，重新执行第 2 步的交互命令即可。

## 4. 不要做的事

- 不要把 `home/` 提交到 git，里面有密码和登录令牌。
- 不要给这个容器映射端口，也不要把它暴露到公网。
- 不要把 `HealthData` 挂成只读，否则同步无法落库。
