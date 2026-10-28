/*
 * 模块说明：2.0 双键壳层状态机；详情页按设计稿拆成多屏幻灯片。
 */
#include "swim_shell.h"

#include "application.h"
#include "custom_lcd_display.h"
#include "swim_coach.h"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <map>

namespace {

constexpr const char* kTag = "SwimShell";
/* 设备字体约 20px，三卡会挤；改为两张加高卡，窗口滚动。 */
constexpr int kListVisible = 2;

/* 趋势跨度展示：1W/1M/1Y → 设计稿「1周/1个月/1年」。 */
std::string FormatTrendSpanLabel(const std::string& span_or_label) {
    if (span_or_label.empty()) {
        return "";
    }
    std::string s = span_or_label;
    char u = static_cast<char>(std::toupper(static_cast<unsigned char>(s.back())));
    if ((u == 'W' || u == 'M' || u == 'Y') && s.size() >= 2) {
        const std::string num = s.substr(0, s.size() - 1);
        if (u == 'W') {
            return num + "周";
        }
        if (u == 'M') {
            return num + "个月";
        }
        return num + "年";
    }
    return s;
}

struct AdviceGuideArgs {
    SwimShell* self = nullptr;
    int gen = 0;
    std::string text;
};

struct AdviceTurnArgs {
    SwimShell* self = nullptr;
    int gen = 0;
    std::string text;
};

struct AdviceSpeakArgs {
    SwimShell* self = nullptr;
    int gen = 0;
    std::string reply;
    bool continue_listen = true;
    AdviceTurnResult turn;
};

const char* DesignTitle(const std::string& page_id, const std::string& fallback, bool session_mode) {
    /* 标题对齐 design/untitled.pen：单次 overview=本场速览；趋势 overview=区间概览。 */
    if (page_id == "overview") {
        return session_mode ? "本场速览" : "区间概览";
    }
    if (page_id == "efficiency") {
        return "效率分析";
    }
    if (page_id == "endurance") {
        return "耐力表现";
    }
    if (page_id == "stability") {
        return "稳定性";
    }
    if (page_id == "next_step") {
        return "下一步";
    }
    if (page_id == "progress") {
        return "进步";
    }
    if (page_id == "load") {
        return "负荷";
    }
    if (!fallback.empty()) {
        return fallback.c_str();
    }
    return "报告";
}

int PageOrder(const std::string& page_id) {
    static const std::map<std::string, int> kOrder = {
        {"overview", 0},   {"efficiency", 1}, {"endurance", 2}, {"stability", 3},
        {"next_step", 4},  {"progress", 1},   {"load", 2},
    };
    auto it = kOrder.find(page_id);
    return it == kOrder.end() ? 50 : it->second;
}

std::vector<ReportPage> OrderedPages(const AnalysisReport& report) {
    std::vector<ReportPage> pages = report.pages;
    std::stable_sort(pages.begin(), pages.end(), [](const ReportPage& a, const ReportPage& b) {
        return PageOrder(a.page_id) < PageOrder(b.page_id);
    });
    return pages;
}

void PushMetricSlide(std::vector<ShellReportSlide>* out, const std::string& title,
                     const std::vector<ReportPageMetric>& metrics, size_t begin, size_t end) {
    if (begin >= end || begin >= metrics.size()) {
        return;
    }
    ShellReportSlide slide;
    slide.title = title;
    for (size_t i = begin; i < end && i < metrics.size(); ++i) {
        slide.metrics.push_back(metrics[i]);
    }
    slide.show_more = true;
    out->push_back(std::move(slide));
}

/* 一屏最多 3 条指标，超出连续翻到下一屏（同标题），避免底部被裁切。 */
constexpr size_t kMetricsPerSlide = 3;
/* AI 说明：正文宽 138；纯说明页约 4 行，折线下方约 2 行（与 ShowShell* 布局对齐）。 */
constexpr int kAiNoteWidth = 138;
constexpr int kAiLinesPerPage = 4;
constexpr int kChartNoteLinesPerPage = 2;

void MarkShowMore(std::vector<ShellReportSlide>* out) {
    if (out == nullptr || out->empty()) {
        return;
    }
    out->back().show_more = false;
    for (size_t i = 0; i + 1 < out->size(); ++i) {
        out->at(i).show_more = true;
    }
}

std::string JoinNotes(const std::vector<std::string>& notes) {
    std::string joined;
    for (const auto& n : notes) {
        if (n.empty()) {
            continue;
        }
        if (!joined.empty()) {
            joined += '\n';
        }
        joined += n;
    }
    return joined;
}

/* AI 说明按行宽连续拆多屏（同标题）；末句显示完才进入下一主题。 */
void PushNoteChunks(std::vector<ShellReportSlide>* out, CustomLcdDisplay* display, const std::string& title,
                    const std::vector<std::string>& notes) {
    if (out == nullptr) {
        return;
    }
    const std::string joined = JoinNotes(notes);
    if (joined.empty()) {
        return;
    }
    std::vector<std::string> chunks;
    if (display != nullptr) {
        chunks = display->PaginateShellAiText(joined, kAiNoteWidth, kAiLinesPerPage);
    }
    if (chunks.empty()) {
        chunks.push_back(joined);
    }
    for (auto& chunk : chunks) {
        ShellReportSlide slide;
        slide.title = title;
        slide.notes = {std::move(chunk)};
        slide.show_more = true;
        out->push_back(std::move(slide));
    }
}

void PushMetricChunks(std::vector<ShellReportSlide>* out, const std::string& title,
                      const std::vector<ReportPageMetric>& metrics) {
    if (metrics.empty()) {
        return;
    }
    for (size_t i = 0; i < metrics.size(); i += kMetricsPerSlide) {
        PushMetricSlide(out, title, metrics, i, std::min(i + kMetricsPerSlide, metrics.size()));
    }
}

/* 按设计稿把 API pages 拆成：本场速览 → 效率 → 耐力 → 稳定性（→ 下一步）。 */
void BuildDesignSlides(const AnalysisReport& report, std::vector<ShellReportSlide>* out,
                       CustomLcdDisplay* display, bool session_mode) {
    out->clear();
    auto pages = OrderedPages(report);
    for (size_t pi = 0; pi < pages.size(); ++pi) {
        const auto& page = pages[pi];
        const std::string title = DesignTitle(page.page_id, page.title, session_mode);

        if (page.page_id == "next_step") {
            /* 下一步以说明为主；若有指标先铺指标，再连续翻完说明。 */
            PushMetricChunks(out, title, page.metrics);
            PushNoteChunks(out, display, title, page.notes);
            continue;
        }
        /* 指标连续分页；说明单独接在后面，长文多页同标题。 */
        PushMetricChunks(out, title, page.metrics);
        PushNoteChunks(out, display, title, page.notes);
    }

    if (out->empty() && !report.one_liner.empty()) {
        PushNoteChunks(out, display, session_mode ? "本场速览" : "区间概览", {report.one_liner});
    }

    MarkShowMore(out);
}

}  // namespace

SwimShell& SwimShell::Get() {
    static SwimShell instance;
    return instance;
}

void SwimShell::Attach(CustomLcdDisplay* display) {
    display_ = display;
}

void SwimShell::ShowHome() {
    StopTrendPoll();
    StopAdviceSession();
    active_ = true;
    focus_ = 0;
    detail_page_ = 0;
    status_line_.clear();
    slides_.clear();
    SetScreen(Screen::Home);
    Render();
}

void SwimShell::Refresh() {
    if (!active_ || display_ == nullptr) {
        return;
    }
    Render();
}

void SwimShell::SetScreen(Screen screen) {
    screen_ = screen;
    if (screen != Screen::TrendAnalyzing) {
        StopTrendPoll();
    }
}

void SwimShell::EnterMainMenu() {
    StopTrendPoll();
    StopAdviceSession();
    focus_ = 0;
    SetScreen(Screen::MainMenu);
    Render();
}

void SwimShell::OnAClick() {
    if (!active_ || display_ == nullptr) {
        return;
    }
    /* 详情翻页优先：避免建议语音态吞掉计划/档案页 A 单击。 */
    if (screen_ == Screen::SessionDetail || screen_ == Screen::TrendDetail ||
        screen_ == Screen::PlanDetail || screen_ == Screen::AdviceProfile) {
        NextDetailPage(-1);
        return;
    }
    /* 聆听中 A 单击 = 打断本段（不提交）。 */
    if (IsAdviceVoiceScreen() && advice_phase_ == AdvicePhase::Listening) {
        InterruptAdviceListening();
        return;
    }
    if (advice_phase_ == AdvicePhase::SpeakingGuide || advice_phase_ == AdvicePhase::SpeakingReply ||
        advice_phase_ == AdvicePhase::Analyzing || screen_ == Screen::AdviceAnalyzing) {
        CancelSwimCoach();
        Application::GetInstance().GetAudioService().ResetDecoder();
        Application::GetInstance().FinishCoachTurn();
        advice_generation_++;
        advice_discard_next_.store(true);
        /* 计划分析中页：打断只停语音，不重开聆听。 */
        if (screen_ == Screen::AdviceAnalyzing &&
            advice_plan_status_.status == "analyzing") {
            return;
        }
        /* 改档播报中打断 → 二级页再听；枢纽播报打断 → Idle；采访 → 再听。 */
        if (screen_ == Screen::AdviceModify) {
            StartAdviceListening();
            return;
        }
        if (screen_ == Screen::AdviceHub) {
            advice_phase_ = AdvicePhase::Idle;
            advice_status_.clear();
            Render();
            return;
        }
        if (screen_ == Screen::Advice || screen_ == Screen::AdviceAnalyzing) {
            StartAdviceListening();
        }
        return;
    }
    MoveFocus(-1);
}

void SwimShell::OnBClick() {
    if (!active_ || display_ == nullptr) {
        return;
    }
    if (screen_ == Screen::SessionDetail || screen_ == Screen::TrendDetail ||
        screen_ == Screen::PlanDetail || screen_ == Screen::AdviceProfile) {
        NextDetailPage(1);
        return;
    }
    MoveFocus(1);
}

void SwimShell::OnADoubleClick() {
    if (!active_ || display_ == nullptr) {
        return;
    }
    /* 聆听中 A 双击 = 确认本轮结束并提交。 */
    if (IsAdviceVoiceScreen() && advice_phase_ == AdvicePhase::Listening) {
        ConfirmAdviceUtterance();
        return;
    }
    Confirm();
}

void SwimShell::OnALongPress() {
    if (!active_ || display_ == nullptr) {
        return;
    }
    GoBack();
}

void SwimShell::OnBDoubleClick() {
    if (!active_ || display_ == nullptr) {
        return;
    }
    ShowHome();
}

void SwimShell::Confirm() {
    switch (screen_) {
        case Screen::Home:
            EnterMainMenu();
            break;
        case Screen::MainMenu:
            if (focus_ == 0) {
                display_->ShowShellText("加载场次...");
                LoadSessions();
                focus_ = 0;
                list_window_ = 0;
                SetScreen(Screen::SessionList);
                Render();
            } else if (focus_ == 1) {
                display_->ShowShellText("加载趋势...");
                LoadTrends();
                focus_ = 0;
                SetScreen(Screen::TrendGrid);
                Render();
            } else {
                EnterAdvice();
            }
            break;
        case Screen::SessionList:
            OpenFocusedSession();
            break;
        case Screen::TrendGrid:
            OpenFocusedTrend();
            break;
        case Screen::Advice:
            /* 采访页非聆听：无操作（聆听已在 OnADoubleClick 拦截） */
            break;
        case Screen::AdviceHub:
            if (advice_phase_ == AdvicePhase::Listening) {
                ConfirmAdviceUtterance();
                break;
            }
            if (advice_phase_ != AdvicePhase::Idle) {
                break;
            }
            if (focus_ == 0) {
                OpenAdviceProfile();
            } else if (focus_ == 1) {
                BeginAdviceModify();
            } else if (focus_ == 2) {
                OpenAdvicePlan();
            } else {
                StartAdvicePlanGenerate();
            }
            break;
        case Screen::AdviceAnalyzing:
        case Screen::AdviceProfile:
        case Screen::AdviceModify:
            break;
        case Screen::PlanDetail:
        case Screen::SessionDetail:
        case Screen::TrendDetail:
        case Screen::TrendAnalyzing:
        case Screen::TrendEmpty:
            break;
    }
}

void SwimShell::GoBack() {
    switch (screen_) {
        case Screen::Home:
            break;
        case Screen::MainMenu:
            ShowHome();
            break;
        case Screen::SessionList:
        case Screen::TrendGrid:
        case Screen::Advice:
        case Screen::AdviceHub:
        case Screen::AdviceAnalyzing:
            EnterMainMenu();
            break;
        case Screen::AdviceProfile:
            detail_page_ = 0;
            profile_slides_.clear();
            EnterAdviceHub();
            break;
        case Screen::AdviceModify:
            StopAdviceSession();
            EnterAdviceHub();
            break;
        case Screen::PlanDetail:
            detail_page_ = 0;
            plan_slides_.clear();
            /* 回枢纽 Idle，不再自动开麦。 */
            EnterAdviceHub();
            break;
        case Screen::SessionDetail:
            detail_page_ = 0;
            slides_.clear();
            SetScreen(Screen::SessionList);
            Render();
            break;
        case Screen::TrendDetail:
        case Screen::TrendAnalyzing:
        case Screen::TrendEmpty:
            detail_page_ = 0;
            report_ = {};
            slides_.clear();
            SetScreen(Screen::TrendGrid);
            Render();
            break;
    }
}

int SwimShell::FocusCount() const {
    switch (screen_) {
        case Screen::MainMenu:
            return 3;
        case Screen::AdviceHub:
            /* 非 Idle 时不换焦，避免改档听麦时误切按钮。 */
            return advice_phase_ == AdvicePhase::Idle ? 4 : 0;
        case Screen::SessionList:
            return static_cast<int>(sessions_.size());
        case Screen::TrendGrid:
            return static_cast<int>(trends_.size());
        default:
            return 0;
    }
}

void SwimShell::MoveFocus(int delta) {
    const int n = FocusCount();
    if (n <= 0) {
        return;
    }
    int next = focus_ + delta;
    if (next < 0 || next >= n) {
        return;
    }
    focus_ = next;
    if (screen_ == Screen::SessionList) {
        if (focus_ < list_window_) {
            list_window_ = focus_;
        } else if (focus_ >= list_window_ + kListVisible) {
            list_window_ = focus_ - kListVisible + 1;
        }
    }
    Render();
}

int SwimShell::DetailPageCount() const {
    if (screen_ == Screen::PlanDetail) {
        return static_cast<int>(plan_slides_.size());
    }
    if (screen_ == Screen::AdviceProfile) {
        return static_cast<int>(profile_slides_.size());
    }
    return static_cast<int>(slides_.size());
}

bool SwimShell::IsAdviceVoiceScreen() const {
    return screen_ == Screen::Advice || screen_ == Screen::AdviceHub ||
           screen_ == Screen::AdviceModify;
}


void SwimShell::NextDetailPage(int delta) {
    const int n = DetailPageCount();
    if (n <= 0) {
        return;
    }
    int next = detail_page_ + delta;
    if (next < 0 || next >= n) {
        return;
    }
    detail_page_ = next;
    Render();
}

void SwimShell::RebuildPlanSlides() {
    plan_slides_.clear();
    for (size_t i = 0; i < advice_plan_.pages.size(); ++i) {
        const auto& page = advice_plan_.pages[i];
        ShellReportSlide slide;
        slide.title = page.title;
        slide.repeat_badge = page.repeat_badge;
        slide.metrics = page.metrics;
        slide.show_more = (i + 1 < advice_plan_.pages.size());
        plan_slides_.push_back(std::move(slide));
    }
}

void SwimShell::EnterAdvice() {
    display_->ShowShellText("加载建议...");
    StopAdviceSession();
    advice_profile_ = {};
    advice_plan_status_ = {};
    profile_slides_.clear();
    std::string err;
    if (!SwimApiFetchAdviceProfile(&advice_profile_, &err)) {
        ESP_LOGW(kTag, "advice profile: %s", err.c_str());
        advice_profile_.guide_text =
            "告诉我您的年纪、身高、体重、性别、训练目标，"
            "以及常游泳池是25米还是50米，我可以给你一些训练建议。";
        advice_profile_.has_profile = false;
    }
    if (advice_profile_.guide_text.empty()) {
        advice_profile_.guide_text =
            "告诉我您的年纪、身高、体重、性别、训练目标，"
            "以及常游泳池是25米还是50米，我可以给你一些训练建议。";
    }
    if (!advice_profile_.slots_complete) {
        /* 槽位未齐：Jtixc 采访，引导 TTS → 听麦 */
        advice_plan_status_.status = "idle";
        advice_plan_status_.can_open = false;
        advice_status_ = "正在回复...";
        advice_phase_ = AdvicePhase::SpeakingGuide;
        SetScreen(Screen::Advice);
        Render();
        BeginAdviceGuide();
        return;
    }
    /* 齐档：直接进枢纽，不开麦 */
    if (!SwimApiFetchAdvicePlanStatus(&advice_plan_status_, &err)) {
        ESP_LOGW(kTag, "advice status: %s", err.c_str());
        advice_plan_status_.status = "idle";
        advice_plan_status_.can_open = false;
    }
    EnterAdviceHub();
}

void SwimShell::EnterAdviceHub() {
    StopAdvicePlanPoll();
    CancelSwimCoach();
    Application::GetInstance().StopListening();
    Application::GetInstance().FinishCoachTurn();
    advice_modify_mode_ = false;
    advice_phase_ = AdvicePhase::Idle;
    advice_status_.clear();
    focus_ = 0;
    SetScreen(Screen::AdviceHub);
    Render();
}

void SwimShell::OpenAdviceProfile() {
    /* 打开档案时重新拉一次，避免枢纽缓存缺「训练难度」等新字段 */
    {
        AdviceProfile refreshed;
        std::string err;
        if (SwimApiFetchAdviceProfile(&refreshed, &err)) {
            advice_profile_ = std::move(refreshed);
        } else {
            ESP_LOGW(kTag, "advice profile refresh: %s", err.c_str());
        }
    }
    RebuildProfileSlides();
    if (profile_slides_.empty()) {
        status_line_ = "暂无档案字段";
        /* 仍进一页空态，避免无反馈 */
        ShellReportSlide empty;
        empty.title = "个人档案";
        empty.show_more = false;
        profile_slides_.push_back(std::move(empty));
    }
    detail_page_ = 0;
    advice_phase_ = AdvicePhase::Idle;
    advice_status_.clear();
    SetScreen(Screen::AdviceProfile);
    Render();
}

void SwimShell::BeginAdviceModify() {
    /* 二级页：展示可收集字段 → TTS → 开麦。 */
    StopAdvicePlanPoll();
    CancelSwimCoach();
    Application::GetInstance().StopListening();
    Application::GetInstance().FinishCoachTurn();
    if (advice_profile_.modify_guide_text.empty()) {
        advice_profile_.modify_guide_text =
            "可修改：性别、年纪、身高、体重、泳池、训练目标。"
            "例如：泳池二十五米；身高一百八十。";
    }
    advice_modify_mode_ = true;
    const int gen = ++advice_generation_;
    advice_discard_next_.store(false);
    advice_phase_ = AdvicePhase::SpeakingGuide;
    advice_status_ = "正在回复...";
    SetScreen(Screen::AdviceModify);
    Render();
    auto* args = new AdviceGuideArgs{this, gen, "请说要改的内容。"};
    if (xTaskCreate(
            [](void* arg) {
                auto* a = static_cast<AdviceGuideArgs*>(arg);
                ClearSwimCoachCancel();
                SpeakSwimCoach(a->text);
                Application::GetInstance().Schedule([self = a->self, gen = a->gen]() {
                    if (gen != self->advice_generation_.load()) {
                        return;
                    }
                    if (!self->active_ || self->screen_ != Screen::AdviceModify) {
                        return;
                    }
                    self->StartAdviceListening();
                });
                Application::GetInstance().FinishCoachTurn();
                delete a;
                vTaskDelete(nullptr);
            },
            "advice_modify", 24576, args, 3, nullptr) != pdPASS) {
        delete args;
        StartAdviceListening();
    }
}

void SwimShell::RebuildProfileSlides() {
    profile_slides_.clear();
    constexpr int kPerPage = 4;
    const auto& fields = advice_profile_.fields;
    for (size_t i = 0; i < fields.size(); i += static_cast<size_t>(kPerPage)) {
        ShellReportSlide slide;
        slide.title = "个人档案";
        const size_t end = std::min(fields.size(), i + static_cast<size_t>(kPerPage));
        for (size_t j = i; j < end; ++j) {
            ReportPageMetric m;
            m.label = fields[j].label;
            m.value = fields[j].value;
            slide.metrics.push_back(std::move(m));
        }
        slide.show_more = end < fields.size();
        profile_slides_.push_back(std::move(slide));
    }
}

void SwimShell::OpenAdvicePlan() {
    /* 「训练计划」：只打开已有计划；没有则提示去点「更新计划」。 */
    if (!advice_profile_.has_profile && !advice_profile_.slots_complete) {
        return;
    }
    if (!advice_plan_status_.can_open) {
        if (advice_plan_status_.status == "analyzing") {
            EnterAdvicePlanAnalyzing();
            return;
        }
        /* 勿在主循环里 delay，会卡住 LVGL/按键；短提示后回枢纽。 */
        display_->ShowShellText("暂无计划\n请选「修改/生成计划」");
        Application::GetInstance().Schedule([this]() {
            if (active_ && screen_ == Screen::AdviceHub) {
                Render();
            }
        });
        return;
    }
    display_->ShowShellText("打开计划...");
    std::string err;
    if (!SwimApiFetchAdvicePlan(&advice_plan_, &err) || advice_plan_.pages.empty()) {
        ESP_LOGW(kTag, "advice plan: %s", err.c_str());
        status_line_ = "计划打开失败";
        Render();
        return;
    }
    /* 进计划页前关掉听麦/TTS，避免 A 单击被语音态吃掉。 */
    StopAdvicePlanPoll();
    advice_phase_ = AdvicePhase::Idle;
    advice_status_.clear();
    CancelSwimCoach();
    Application::GetInstance().StopListening();
    Application::GetInstance().FinishCoachTurn();
    RebuildPlanSlides();
    detail_page_ = 0;
    SetScreen(Screen::PlanDetail);
    Render();
}

void SwimShell::StartAdvicePlanGenerate() {
    /* 「修改/生成计划」：无论有无旧计划都入队重新生成。 */
    if (!advice_profile_.has_profile && !advice_profile_.slots_complete) {
        return;
    }
    if (advice_plan_status_.status == "analyzing") {
        EnterAdvicePlanAnalyzing();
        return;
    }
    AdvicePlanStatus st;
    std::string err;
    if (SwimApiAnalyzeAdvicePlan(false, &st, &err)) {
        advice_plan_status_ = st;
    } else {
        ESP_LOGW(kTag, "advice analyze: %s", err.c_str());
        display_->ShowShellText("启动失败");
        Application::GetInstance().Schedule([this]() {
            if (active_ && screen_ == Screen::AdviceHub) {
                Render();
            }
        });
        return;
    }
    EnterAdvicePlanAnalyzing();
}

void SwimShell::LoadSessions() {
    std::string err;
    sessions_.clear();
    if (!SwimApiFetchSessions(&sessions_, &err)) {
        ESP_LOGW(kTag, "sessions fail: %s", err.c_str());
        status_line_ = "无法加载场次";
    } else {
        status_line_.clear();
    }
}

void SwimShell::LoadTrends() {
    std::string err;
    trends_.clear();
    if (!SwimApiFetchTrends(&trends_, &err)) {
        ESP_LOGW(kTag, "trends fail: %s", err.c_str());
        status_line_ = "无法加载趋势";
    } else {
        status_line_.clear();
    }
}

void SwimShell::RebuildSessionSlides() {
    BuildDesignSlides(report_, &slides_, display_, true);
}

void SwimShell::RebuildTrendSlides() {
    BuildDesignSlides(report_, &slides_, display_, false);
    /* 趋势图表接在文字页之后；图下 AI 说明过长则同标题续页（仅首页画折线）。 */
    for (size_t i = 0; i < report_.charts.size(); ++i) {
        const auto& chart = report_.charts[i];
        const std::string title = chart.title.empty() ? "趋势图" : chart.title;
        std::vector<std::string> chunks;
        if (!chart.note.empty() && display_ != nullptr) {
            chunks = display_->PaginateShellAiText(chart.note, kAiNoteWidth, kChartNoteLinesPerPage);
        }
        if (chunks.empty() && !chart.note.empty()) {
            chunks.push_back(chart.note);
        }
        if (chunks.empty()) {
            ShellReportSlide slide;
            slide.title = title;
            slide.chart_index = static_cast<int>(i);
            slide.draw_chart = true;
            slides_.push_back(std::move(slide));
            continue;
        }
        for (size_t ci = 0; ci < chunks.size(); ++ci) {
            ShellReportSlide slide;
            slide.title = title;
            slide.notes = {chunks[ci]};
            slide.chart_index = static_cast<int>(i);
            slide.draw_chart = (ci == 0);
            slides_.push_back(std::move(slide));
        }
    }
    MarkShowMore(&slides_);
}

void SwimShell::OpenFocusedSession() {
    if (focus_ < 0 || focus_ >= static_cast<int>(sessions_.size())) {
        return;
    }
    const auto& row = sessions_[focus_];
    if (!row.can_open) {
        return;
    }
    display_->ShowShellText("打开报告...");
    AnalysisReport report;
    std::string err;
    if (!SwimApiFetchSessionReport(row.activity_id, &report, &err)) {
        ESP_LOGW(kTag, "session report fail: %s", err.c_str());
        status_line_ = "报告打开失败";
        Render();
        return;
    }
    report_ = std::move(report);
    RebuildSessionSlides();
    detail_page_ = 0;
    SetScreen(Screen::SessionDetail);
    Render();
}

void SwimShell::OpenFocusedTrend() {
    if (focus_ < 0 || focus_ >= static_cast<int>(trends_.size())) {
        return;
    }
    const auto& row = trends_[focus_];
    /* API 跨度为小写 1w/6m；统一小写避免 status/analyze 404。 */
    trend_span_ = row.span;
    for (char& c : trend_span_) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    trend_label_ = !row.span.empty() ? row.span : row.label;

    display_->ShowShellText("请求分析...");
    TrendAnalyzeResult result;
    std::string err;
    if (!SwimApiAnalyzeTrend(trend_span_, &result, &err)) {
        ESP_LOGW(kTag, "analyze fail: %s", err.c_str());
        status_line_ = "请求失败";
        SetScreen(Screen::TrendEmpty);
        Render();
        return;
    }
    if (result.can_open) {
        OpenTrendReport();
        return;
    }
    status_line_.clear();
    SetScreen(Screen::TrendAnalyzing);
    Render();
    StartTrendPoll();
}

void SwimShell::OpenTrendReport() {
    AnalysisReport report;
    std::string err;
    if (!SwimApiFetchTrendReport(trend_span_, &report, &err)) {
        ESP_LOGW(kTag, "trend report fail: %s", err.c_str());
        status_line_ = "报告打开失败";
        SetScreen(Screen::TrendEmpty);
        Render();
        return;
    }
    if (report.sample_insufficient || report.session_count <= 0) {
        report_ = std::move(report);
        slides_.clear();
        SetScreen(Screen::TrendEmpty);
        Render();
        return;
    }
    report_ = std::move(report);
    RebuildTrendSlides();
    detail_page_ = 0;
    SetScreen(Screen::TrendDetail);
    Render();
}

void SwimShell::StartTrendPoll() {
    const int gen = ++poll_generation_;
    xTaskCreate(
        &SwimShell::TrendPollTask, "trend_poll", 8192, reinterpret_cast<void*>(static_cast<intptr_t>(gen)), 3,
        nullptr);
}

void SwimShell::StopTrendPoll() {
    ++poll_generation_;
}

void SwimShell::TrendPollTask(void* arg) {
    const int gen = static_cast<int>(reinterpret_cast<intptr_t>(arg));
    auto& self = SwimShell::Get();
    while (self.poll_generation_.load() == gen) {
        vTaskDelay(pdMS_TO_TICKS(2000));
        if (self.poll_generation_.load() != gen) {
            break;
        }
        TrendAnalyzeResult st;
        std::string err;
        if (!SwimApiTrendStatus(self.trend_span_, &st, &err)) {
            ESP_LOGW(kTag, "status fail: %s", err.c_str());
            continue;
        }
        /* succeeded：无论 can_open，都拉报告（样本不足会进无数据页）。 */
        if (st.status == "succeeded") {
            Application::GetInstance().Schedule([&self, gen]() {
                if (self.poll_generation_.load() != gen) {
                    return;
                }
                self.StopTrendPoll();
                self.OpenTrendReport();
            });
            break;
        }
        if (st.status == "failed" || st.status == "idle") {
            const std::string st_copy = st.status;
            Application::GetInstance().Schedule([&self, gen, st_copy]() {
                if (self.poll_generation_.load() != gen) {
                    return;
                }
                self.StopTrendPoll();
                self.status_line_ = (st_copy == "failed") ? "分析失败" : "暂无游泳记录";
                self.SetScreen(Screen::TrendEmpty);
                self.Render();
            });
            break;
        }
    }
    vTaskDelete(nullptr);
}

void SwimShell::Render() {
    if (display_ == nullptr) {
        return;
    }
    switch (screen_) {
        case Screen::Home:
            display_->ShowShellHome();
            break;
        case Screen::MainMenu:
            display_->ShowShellMenu(focus_);
            break;
        case Screen::SessionList:
            display_->ShowShellSessions(sessions_, focus_, list_window_, status_line_);
            break;
        case Screen::SessionDetail:
        case Screen::TrendDetail: {
            if (slides_.empty()) {
                display_->ShowShellText("无报告内容");
                break;
            }
            const int idx = std::min(detail_page_, static_cast<int>(slides_.size()) - 1);
            const auto& slide = slides_[idx];
            /* 趋势折线：仅首页画图；续页用同一标题的 AI 说明页，避免半句跳主题。 */
            if (slide.draw_chart && slide.chart_index >= 0 &&
                slide.chart_index < static_cast<int>(report_.charts.size())) {
                const auto& c = report_.charts[slide.chart_index];
                const std::string note = slide.notes.empty() ? c.note : slide.notes.front();
                display_->ShowShellChart(slide.title, c.values, note);
                break;
            }
            display_->ShowShellReportPage(slide.title, slide.metrics, slide.notes, slide.show_more);
            break;
        }
        case Screen::TrendGrid:
            display_->ShowShellTrends(trends_, focus_, status_line_);
            break;
        case Screen::TrendAnalyzing: {
            /* 对齐设计稿 sOxZo：分析中 + 主视觉 + 跨度 + 正在分析中… */
            display_->ShowShellTrendStatus(true, FormatTrendSpanLabel(trend_label_), "正在分析中…",
                                          "完成后自动进入详情");
            break;
        }
        case Screen::TrendEmpty: {
            /* 对齐设计稿 D1yOTx：无数据 + 主视觉 + 跨度 + 暂无记录。 */
            std::string primary = "暂无游泳记录";
            std::string secondary = "换更大跨度或先同步";
            if (!status_line_.empty()) {
                primary = status_line_;
                secondary.clear();
            }
            display_->ShowShellTrendStatus(false, FormatTrendSpanLabel(trend_label_), primary, secondary);
            break;
        }
        case Screen::AdviceAnalyzing: {
            /* 对齐 sOxZo：全屏分析中，等 /advice/turn 或计划轮询。 */
            display_->ShowShellTrendStatus(true, "", "正在分析…", "整理档案与计划");
            break;
        }
        case Screen::Advice: {
            /* Jtixc：无档案采访，无 CTA */
            const std::string& body = advice_profile_.guide_text.empty()
                                         ? advice_profile_.summary_text
                                         : advice_profile_.guide_text;
            display_->ShowShellAdvice(advice_status_, body, "hidden");
            break;
        }
        case Screen::AdviceHub: {
            const bool plan_ready = advice_plan_status_.can_open;
            const bool plan_analyzing = advice_plan_status_.status == "analyzing";
            display_->ShowShellAdviceHub(advice_status_, focus_, plan_ready, plan_analyzing);
            break;
        }
        case Screen::AdviceModify: {
            /* 二级页：Logo+状态 + 可收集字段说明（无 CTA）。 */
            const std::string& body = advice_profile_.modify_guide_text.empty()
                                         ? advice_profile_.guide_text
                                         : advice_profile_.modify_guide_text;
            display_->ShowShellAdvice(advice_status_, body, "hidden");
            break;
        }
        case Screen::AdviceProfile: {
            if (profile_slides_.empty()) {
                display_->ShowShellText("暂无档案");
                break;
            }
            const int idx = std::min(detail_page_, static_cast<int>(profile_slides_.size()) - 1);
            const auto& slide = profile_slides_[idx];
            display_->ShowShellReportPage(slide.title, slide.metrics, slide.notes, slide.show_more);
            break;
        }
        case Screen::PlanDetail: {
            if (plan_slides_.empty()) {
                display_->ShowShellText("无计划内容");
                break;
            }
            const int idx = std::min(detail_page_, static_cast<int>(plan_slides_.size()) - 1);
            const auto& slide = plan_slides_[idx];
            display_->ShowShellPlanPage(slide.title, slide.repeat_badge, slide.metrics, slide.show_more);
            break;
        }
    }
}

void SwimShell::StopAdviceSession() {
    advice_generation_++;
    advice_discard_next_.store(true);
    advice_phase_ = AdvicePhase::Idle;
    advice_modify_mode_ = false;
    advice_status_.clear();
    StopAdvicePlanPoll();
    CancelSwimCoach();
    auto& app = Application::GetInstance();
    if (app.GetDeviceState() == kDeviceStateListening) {
        app.StopListening();
    }
    app.FinishCoachTurn();
}

void SwimShell::EnterAdvicePlanAnalyzing() {
    advice_phase_ = AdvicePhase::Analyzing;
    advice_status_.clear();
    advice_plan_status_.status = "analyzing";
    CancelSwimCoach();
    Application::GetInstance().StopListening();
    Application::GetInstance().FinishCoachTurn();
    SetScreen(Screen::AdviceAnalyzing);
    Render();
    StartAdvicePlanPoll();
}

void SwimShell::StartAdvicePlanPoll() {
    const int gen = ++advice_plan_poll_generation_;
    xTaskCreate(&SwimShell::AdvicePlanPollTask, "advice_plan_poll", 8192,
                reinterpret_cast<void*>(static_cast<intptr_t>(gen)), 3, nullptr);
}

void SwimShell::StopAdvicePlanPoll() {
    ++advice_plan_poll_generation_;
}

void SwimShell::AdvicePlanPollTask(void* arg) {
    const int gen = static_cast<int>(reinterpret_cast<intptr_t>(arg));
    auto& self = SwimShell::Get();
    while (self.advice_plan_poll_generation_.load() == gen) {
        vTaskDelay(pdMS_TO_TICKS(2000));
        if (self.advice_plan_poll_generation_.load() != gen) {
            break;
        }
        AdvicePlanStatus st;
        std::string err;
        if (!SwimApiFetchAdvicePlanStatus(&st, &err)) {
            ESP_LOGW(kTag, "advice plan status: %s", err.c_str());
            continue;
        }
        if (st.status == "succeeded" && st.can_open) {
            Application::GetInstance().Schedule([&self, gen, st]() {
                if (self.advice_plan_poll_generation_.load() != gen) {
                    return;
                }
                self.StopAdvicePlanPoll();
                self.advice_plan_status_ = st;
                self.EnterAdviceHub();
            });
            break;
        }
        if (st.status == "failed") {
            Application::GetInstance().Schedule([&self, gen, st]() {
                if (self.advice_plan_poll_generation_.load() != gen) {
                    return;
                }
                self.StopAdvicePlanPoll();
                self.advice_plan_status_ = st;
                self.EnterAdviceHub();
            });
            break;
        }
    }
    vTaskDelete(nullptr);
}

void SwimShell::BeginAdviceGuide() {
    const int gen = ++advice_generation_;
    advice_discard_next_.store(false);
    advice_phase_ = AdvicePhase::SpeakingGuide;
    advice_status_ = "正在回复...";
    if (display_ != nullptr && screen_ == Screen::Advice) {
        Render();
    }
    /* 后台播引导/档案摘要，播完再开麦，避免阻塞按键任务。 */
    auto* args = new AdviceGuideArgs{this, gen, {}};
    args->text = advice_profile_.has_profile && !advice_profile_.summary_text.empty()
                     ? advice_profile_.summary_text
                     : advice_profile_.guide_text;
    if (args->text.empty()) {
        args->text = "告诉我您的年纪、身高、体重、性别等信息和训练目标，我可以给你一些训练建议。";
    }
    ESP_LOGI(kTag, "advice guide speak %u bytes", static_cast<unsigned>(args->text.size()));
    if (xTaskCreate(
            [](void* arg) {
                auto* a = static_cast<AdviceGuideArgs*>(arg);
                ClearSwimCoachCancel();
                if (!SpeakSwimCoach(a->text)) {
                    ESP_LOGW(kTag, "advice guide speak failed, retry once");
                    vTaskDelay(pdMS_TO_TICKS(400));
                    ClearSwimCoachCancel();
                    if (!SpeakSwimCoach(a->text)) {
                        ESP_LOGE(kTag, "advice guide speak still failed");
                    }
                }
                Application::GetInstance().Schedule([self = a->self, gen = a->gen]() {
                    if (gen != self->advice_generation_.load()) {
                        return;
                    }
                    if (!self->active_ ||
                        (self->screen_ != Screen::Advice && self->screen_ != Screen::AdviceAnalyzing &&
                         self->screen_ != Screen::AdviceHub)) {
                        return;
                    }
                    self->StartAdviceListening();
                });
                Application::GetInstance().FinishCoachTurn();
                delete a;
                vTaskDelete(nullptr);
            },
            "advice_guide", 24576, args, 3, nullptr) != pdPASS) {
        delete args;
        StartAdviceListening();
    }
}

void SwimShell::StartAdviceListening() {
    if (!active_ || display_ == nullptr) {
        return;
    }
    advice_discard_next_.store(false);
    advice_phase_ = AdvicePhase::Listening;
    advice_status_ = "正在聆听...";
    if (advice_modify_mode_) {
        SetScreen(Screen::AdviceModify);
    } else {
        SetScreen(Screen::Advice);
    }
    Render();
    Application::GetInstance().StartListening();
}

void SwimShell::ConfirmAdviceUtterance() {
    if (advice_phase_ != AdvicePhase::Listening) {
        return;
    }
    advice_discard_next_.store(false);
    /* 与教练 VAD 尾点相同：SendStopListening，等云端 STT。 */
    Application::GetInstance().StopListening();
}

void SwimShell::InterruptAdviceListening() {
    if (advice_phase_ != AdvicePhase::Listening) {
        return;
    }
    advice_discard_next_.store(true);
    Application::GetInstance().StopListening();
    Application::GetInstance().FinishCoachTurn();
    /* 打断后重新开麦，继续采访。 */
    Application::GetInstance().Schedule([this]() {
        if (!active_ || !IsAdviceVoiceScreen()) {
            return;
        }
        if (advice_phase_ != AdvicePhase::Listening && advice_phase_ != AdvicePhase::Idle) {
            return;
        }
        StartAdviceListening();
    });
}

bool SwimShell::TryHandleAdviceUtterance(const std::string& text) {
    if (!active_) {
        return false;
    }
    if (screen_ != Screen::Advice && screen_ != Screen::AdviceHub &&
        screen_ != Screen::AdviceModify && screen_ != Screen::AdviceAnalyzing) {
        return false;
    }
    if (advice_phase_ != AdvicePhase::Listening && advice_phase_ != AdvicePhase::Analyzing) {
        return false;
    }
    if (advice_discard_next_.exchange(false)) {
        ESP_LOGI(kTag, "advice discard utterance");
        Application::GetInstance().FinishCoachTurn();
        if (advice_phase_ == AdvicePhase::Listening || advice_phase_ == AdvicePhase::Idle) {
            StartAdviceListening();
        }
        return true;
    }
    if (text.empty()) {
        Application::GetInstance().FinishCoachTurn();
        StartAdviceListening();
        return true;
    }
    EnqueueAdviceTurn(text);
    return true;
}

void SwimShell::EnqueueAdviceTurn(const std::string& text) {
    if (advice_worker_running_.exchange(true)) {
        ESP_LOGW(kTag, "advice worker busy");
        return;
    }
    const int gen = advice_generation_.load();
    advice_phase_ = AdvicePhase::Analyzing;
    advice_status_ = "正在分析...";
    SetScreen(Screen::AdviceAnalyzing);
    Render();

    auto* args = new AdviceTurnArgs{this, gen, text};
    if (xTaskCreate(AdviceWorkerTask, "advice_turn", 28672, args, 3, nullptr) != pdPASS) {
        delete args;
        advice_worker_running_.store(false);
        Application::GetInstance().FinishCoachTurn();
        StartAdviceListening();
    }
}

void SwimShell::AdviceWorkerTask(void* arg) {
    auto* args = static_cast<AdviceTurnArgs*>(arg);
    SwimShell* self = args->self;
    const int gen = args->gen;
    const std::string text = std::move(args->text);
    delete args;

    AdviceTurnResult turn;
    std::string err;
    const char* mode = self->advice_modify_mode_ ? "modify" : "interview";
    const bool ok = SwimApiPostAdviceTurn(text, &turn, &err, mode);
    if (!ok) {
        ESP_LOGW(kTag, "advice turn: %s", err.c_str());
        turn.reply_text = "这轮没连上，稍后再说一次。";
        if (self->advice_modify_mode_) {
            turn.keep_listening = true;
        }
    }

    Application::GetInstance().Schedule([self, gen, turn = std::move(turn)]() mutable {
        if (gen != self->advice_generation_.load() || !self->active_) {
            self->advice_worker_running_.store(false);
            Application::GetInstance().FinishCoachTurn();
            return;
        }
        if (self->screen_ != Screen::Advice && self->screen_ != Screen::AdviceAnalyzing &&
            self->screen_ != Screen::AdviceHub && self->screen_ != Screen::AdviceModify) {
            self->advice_worker_running_.store(false);
            Application::GetInstance().FinishCoachTurn();
            return;
        }

        self->advice_profile_.has_profile = turn.has_profile;
        self->advice_profile_.slots_complete = turn.slots_complete;
        if (!turn.summary_text.empty()) {
            self->advice_profile_.summary_text = turn.summary_text;
        }
        if (!turn.guide_text.empty()) {
            if (self->advice_modify_mode_) {
                self->advice_profile_.modify_guide_text = turn.guide_text;
            } else {
                self->advice_profile_.guide_text = turn.guide_text;
            }
        }
        if (!turn.fields.empty()) {
            self->advice_profile_.fields = turn.fields;
        }
        if (!turn.plan_status.status.empty()) {
            self->advice_plan_status_ = turn.plan_status;
        }
        /* 已触发出计划：强制 analyzing，避免旧 succeeded 计划把 CTA 画成对勾。 */
        if (turn.start_plan) {
            self->advice_plan_status_.status = "analyzing";
            self->advice_plan_status_.can_open = false;
        }

        self->advice_phase_ = AdvicePhase::SpeakingReply;
        self->advice_status_ = "正在回复...";
        /* 改档：二级页播确认；采访齐档：先回枢纽；未齐：采访页。 */
        if (self->advice_modify_mode_) {
            if (!turn.reply_text.empty()) {
                self->advice_profile_.modify_guide_text = turn.reply_text;
            }
            self->SetScreen(Screen::AdviceModify);
        } else if (turn.slots_complete) {
            self->SetScreen(Screen::AdviceHub);
        } else {
            if (!turn.reply_text.empty()) {
                self->advice_profile_.guide_text = turn.reply_text;
            }
            self->SetScreen(Screen::Advice);
        }
        self->Render();

        const std::string reply =
            turn.reply_text.empty() ? std::string("好的。") : turn.reply_text;
        const bool continue_listen =
            turn.keep_listening || (!turn.slots_complete && !turn.start_plan);
        const bool enter_hub =
            !turn.keep_listening && turn.slots_complete && !turn.start_plan &&
            !self->advice_modify_mode_;
        const bool enter_hub_after_modify =
            self->advice_modify_mode_ && !turn.keep_listening && !turn.start_plan;
        const bool enter_plan_analyzing = turn.start_plan;
        auto* sa = new AdviceSpeakArgs{self, gen, reply, continue_listen, std::move(turn)};
        if (xTaskCreate(
                [](void* p) {
                    auto* s = static_cast<AdviceSpeakArgs*>(p);
                    ClearSwimCoachCancel();
                    SpeakSwimCoach(s->reply);
                    Application::GetInstance().Schedule([s]() {
                        auto* self = s->self;
                        const int gen = s->gen;
                        self->advice_worker_running_.store(false);
                        if (gen != self->advice_generation_.load() || !self->active_) {
                            Application::GetInstance().FinishCoachTurn();
                            delete s;
                            return;
                        }
                        if (s->turn.has_profile && !s->turn.summary_text.empty()) {
                            self->advice_profile_.summary_text = s->turn.summary_text;
                        }
                        if (!s->turn.fields.empty()) {
                            self->advice_profile_.fields = s->turn.fields;
                        }
                        Application::GetInstance().FinishCoachTurn();
                        if (self->screen_ != Screen::Advice && self->screen_ != Screen::AdviceAnalyzing &&
                            self->screen_ != Screen::AdviceHub &&
                            self->screen_ != Screen::AdviceModify) {
                            delete s;
                            return;
                        }
                        if (s->turn.start_plan) {
                            self->EnterAdvicePlanAnalyzing();
                        } else if (s->turn.keep_listening || s->continue_listen) {
                            /* 听不清：屏上恢复可收集说明，继续开麦 */
                            if (self->advice_modify_mode_ && !s->turn.guide_text.empty()) {
                                self->advice_profile_.modify_guide_text = s->turn.guide_text;
                            }
                            self->StartAdviceListening();
                        } else if (self->advice_modify_mode_) {
                            /* 改档成功：回枢纽 */
                            self->EnterAdviceHub();
                        } else if (s->turn.slots_complete) {
                            self->EnterAdviceHub();
                        } else {
                            self->advice_phase_ = AdvicePhase::Idle;
                            self->advice_status_.clear();
                            self->Render();
                        }
                        delete s;
                    });
                    vTaskDelete(nullptr);
                },
                "advice_reply", 24576, sa, 3, nullptr) != pdPASS) {
            delete sa;
            self->advice_worker_running_.store(false);
            Application::GetInstance().FinishCoachTurn();
            if (enter_plan_analyzing) {
                self->EnterAdvicePlanAnalyzing();
            } else if (continue_listen) {
                self->StartAdviceListening();
            } else if (enter_hub_after_modify || enter_hub) {
                self->EnterAdviceHub();
            } else {
                self->StartAdviceListening();
            }
        }
    });

    vTaskDelete(nullptr);
}
