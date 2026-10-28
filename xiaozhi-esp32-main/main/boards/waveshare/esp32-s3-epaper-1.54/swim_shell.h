/*
 * 模块说明：2.0 双键壳层——首页 / 主菜单 / 单次 / 趋势 / 综合建议（计划翻页 + 语音采访）。
 * A=BOOT：上一项/确定(双击)/返回(长按)；B=PWR：下一项/休眠(双击)/关机(长按由板级保留)。
 * 综合建议：无档案采访；有档案枢纽（个人档案/训练计划/修改档案）；齐档后不自动出计划。
 * UI 1:1 对齐 design/untitled.pen（Jtixc / imRzc / sf6J3）。
 */
#pragma once

#include "swim_api_client.h"

#include <atomic>
#include <string>
#include <vector>

class CustomLcdDisplay;

/* 详情翻页单元：对应设计稿一屏（指标页或 AI 说明页）。 */
struct ShellReportSlide {
    std::string title;
    std::string repeat_badge; /* 计划「主要」右侧「3次」；空则不显示 */
    std::vector<ReportPageMetric> metrics;
    std::vector<std::string> notes;
    bool show_more = true;
    /* >=0：本页为趋势折线图（note 可跨多页续读，仅首页画图）。 */
    int chart_index = -1;
    bool draw_chart = false;
};

class SwimShell {
public:
    static SwimShell& Get();

    void Attach(CustomLcdDisplay* display);
    void ShowHome();
    /* 主题/字体变更后重绘当前屏，避免旧 font 指针触发 MMU 崩溃。 */
    void Refresh();

    void OnAClick();
    void OnADoubleClick();
    void OnALongPress();
    void OnBClick();
    void OnBDoubleClick();

    bool IsActive() const { return active_; }
    /* 综合建议聆听中：吃掉 STT，不进日常教练队列。 */
    bool TryHandleAdviceUtterance(const std::string& text);

private:
    enum class Screen {
        Home,
        MainMenu,
        SessionList,
        SessionDetail,
        TrendGrid,
        TrendAnalyzing,
        TrendEmpty,
        TrendDetail,
        Advice,           /* 无档案采访页 */
        AdviceHub,        /* 有档案三按钮枢纽 */
        AdviceProfile,    /* 个人档案翻页 */
        AdviceModify,     /* 修改档案：可收集说明 + 听麦 */
        AdviceAnalyzing,
        PlanDetail,
    };

    /* 综合建议语音子状态。 */
    enum class AdvicePhase {
        Idle,
        SpeakingGuide,
        Listening,
        Analyzing,
        SpeakingReply,
    };

    SwimShell() = default;

    void SetScreen(Screen screen);
    void Render();
    void LoadSessions();
    void LoadTrends();
    void OpenFocusedSession();
    void OpenFocusedTrend();
    void OpenTrendReport();
    void StartTrendPoll();
    void StopTrendPoll();
    static void TrendPollTask(void* arg);
    void MoveFocus(int delta);
    int FocusCount() const;
    int DetailPageCount() const;
    void NextDetailPage(int delta);
    void Confirm();
    void GoBack();
    void EnterMainMenu();
    void RebuildSessionSlides();
    void RebuildTrendSlides();
    void EnterAdvice();
    void EnterAdviceHub();
    void OpenAdviceProfile();
    void OpenAdvicePlan();
    void StartAdvicePlanGenerate(); /* 生成/更新计划（强制入队） */
    void BeginAdviceModify();
    void RebuildPlanSlides();
    void RebuildProfileSlides();

    void StopAdviceSession();
    void BeginAdviceGuide();
    void StartAdviceListening();
    void ConfirmAdviceUtterance();
    void InterruptAdviceListening();
    void EnqueueAdviceTurn(const std::string& text);
    static void AdviceWorkerTask(void* arg);
    /* 出计划后：全屏分析中轮询，直到 succeeded/failed。 */
    void EnterAdvicePlanAnalyzing();
    void StartAdvicePlanPoll();
    void StopAdvicePlanPoll();
    static void AdvicePlanPollTask(void* arg);
    bool IsAdviceVoiceScreen() const;

    CustomLcdDisplay* display_ = nullptr;
    bool active_ = false;
    Screen screen_ = Screen::Home;
    int focus_ = 0;
    int detail_page_ = 0;
    int list_window_ = 0;

    std::string trend_span_;
    std::string trend_label_;
    std::string status_line_;

    std::vector<SessionListItem> sessions_;
    std::vector<TrendListItem> trends_;
    AnalysisReport report_;
    std::vector<ShellReportSlide> slides_;

    AdviceProfile advice_profile_;
    AdvicePlanStatus advice_plan_status_;
    AdvicePlan advice_plan_;
    std::vector<ShellReportSlide> plan_slides_;
    std::vector<ShellReportSlide> profile_slides_;
    AdvicePhase advice_phase_ = AdvicePhase::Idle;
    bool advice_modify_mode_ = false; /* 枢纽「修改档案」二级页会话 */
    std::string advice_status_; /* 右上：正在聆听/正在回复… */
    std::atomic<int> advice_generation_{0};
    std::atomic<bool> advice_discard_next_{false};
    std::atomic<bool> advice_worker_running_{false};
    std::atomic<int> advice_plan_poll_generation_{0};

    std::atomic<int> poll_generation_{0};
};
