#include <stdio.h>
#include <esp_lcd_panel_io.h>
#include <freertos/FreeRTOS.h>
#include <vector>
#include <esp_log.h>
#include "custom_lcd_display.h"
#include "arena_standby.h"
#include "board.h"
#include "config.h"
#include "esp_lvgl_port.h"
#include "settings.h"
#include "assets/lang_config.h"
#include "swim_shell.h"
#include "ian_home.h"
#include "icon_done_black.h"
#include "icon_done_white.h"
#include "icon_analyzing_black.h"
#include "icon_analyzing_white.h"
#include "icon_ai.h"
#include "icon_chevron_down.h"
#include "icon_trend_analyzing.h"
#include "icon_trend_empty.h"
#include "icon_ian_logo.h"


#include <esp_timer.h>

#include <algorithm>
#include <cctype>
#include <cstring>

#define TAG "CustomLcdDisplay"

#define BYTES_PER_PIXEL (LV_COLOR_FORMAT_GET_SIZE(LV_COLOR_FORMAT_RGB565))
#define BUFF_SIZE (EXAMPLE_LCD_WIDTH * EXAMPLE_LCD_HEIGHT * BYTES_PER_PIXEL)

const uint8_t WF_Full_1IN54[159] =
{											
    0x80,0x48,0x40,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x40,0x48,0x80,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x80,0x48,0x40,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x40,0x48,0x80,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0xA,0x0,0x0,0x0,0x0,0x0,0x0,				
    0x8,0x1,0x0,0x8,0x1,0x0,0x2,				
    0xA,0x0,0x0,0x0,0x0,0x0,0x0,				
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,				
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,				
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,				
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,				
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,				
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,				
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,				
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,				
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,				
    0x22,0x22,0x22,0x22,0x22,0x22,0x0,0x0,0x0,			
    0x22,0x17,0x41,0x0,0x32,0x20
};

const uint8_t WF_PARTIAL_1IN54_0[159] =
{
    0x0,0x40,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x80,0x80,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x40,0x40,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x80,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0xF,0x0,0x0,0x0,0x0,0x0,0x0,
    0x1,0x1,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x22,0x22,0x22,0x22,0x22,0x22,0x0,0x0,0x0,
    0x02,0x17,0x41,0xB0,0x32,0x28,
};

void CustomLcdDisplay::lvgl_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *color_p) {
    assert(disp != NULL);
    CustomLcdDisplay *driver = (CustomLcdDisplay *) lv_display_get_user_data(disp);
    uint16_t         *buffer = (uint16_t *) color_p;
    driver->EPD_Clear();
    for (int y = area->y1; y <= area->y2; y++) {
        for (int x = area->x1; x <= area->x2; x++) {
            uint8_t color = (*buffer < 0x7fff) ? DRIVER_COLOR_BLACK : DRIVER_COLOR_WHITE;
            driver->EPD_DrawColorPixel(x, y, color);
            buffer++;
        }
    }
    driver->EPD_DisplayPart();
    lv_disp_flush_ready(disp);
}

CustomLcdDisplay::CustomLcdDisplay(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_handle_t panel, 
    int width, int height, int offset_x, int offset_y, 
    bool mirror_x, bool mirror_y, bool swap_xy, custom_lcd_spi_t _lcd_spi_data) : 
    LcdDisplay(panel_io, panel, width, height), 
    lcd_spi_data(_lcd_spi_data), 
    Width(width), Height(height) {

    ESP_LOGI(TAG, "Initialize SPI");
    spi_port_init();
    spi_gpio_init();

    ESP_LOGI(TAG, "Initialize LVGL library");
    lv_init();

    lvgl_port_cfg_t port_cfg = ESP_LVGL_PORT_INIT_CONFIG();
    port_cfg.task_priority   = 2;
    port_cfg.timer_period_ms = 50;
    lvgl_port_init(&port_cfg);
    lvgl_port_lock(0);

    buffer = (uint8_t *) heap_caps_malloc(lcd_spi_data.buffer_len, MALLOC_CAP_SPIRAM);
    assert(buffer);
    display_ = lv_display_create(width, height); /* 以水平和垂直分辨率（像素）进行基本初始化 */
    lv_display_set_flush_cb(display_, lvgl_flush_cb);
    lv_display_set_user_data(display_, this);

    uint8_t *buffer_1 = NULL;
    buffer_1          = (uint8_t *) heap_caps_malloc(BUFF_SIZE, MALLOC_CAP_SPIRAM);
    assert(buffer_1);
    lv_display_set_buffers(display_, buffer_1, NULL, BUFF_SIZE, LV_DISPLAY_RENDER_MODE_FULL);

    ESP_LOGI(TAG, "EPD init");
    EPD_Init();
    EPD_Clear();
    EPD_Display();
    EPD_DisplayPartBaseImage();
    EPD_Init_Partial(); // 局部刷新初始化

    lvgl_port_unlock();
    if (display_ == nullptr) {
        ESP_LOGE(TAG, "Failed to add display");
        return;
    }

    // Note: SetupUI() should be called by Application::Initialize(), not in constructor
    // to ensure lvgl objects are created after the display is fully initialized.
}

CustomLcdDisplay::~CustomLcdDisplay() {
    
}

void CustomLcdDisplay::spi_gpio_init() {
    int rst  = lcd_spi_data.rst;
    int cs   = lcd_spi_data.cs;
    int dc   = lcd_spi_data.dc;
    int busy = lcd_spi_data.busy;

    gpio_config_t gpio_conf = {};
    gpio_conf.intr_type     = GPIO_INTR_DISABLE;
    gpio_conf.mode          = GPIO_MODE_OUTPUT;
    gpio_conf.pin_bit_mask  = (0x1ULL << rst) | (0x1ULL << dc) | (0x1ULL << cs);
    gpio_conf.pull_down_en  = GPIO_PULLDOWN_DISABLE;
    gpio_conf.pull_up_en    = GPIO_PULLUP_ENABLE;
    ESP_ERROR_CHECK_WITHOUT_ABORT(gpio_config(&gpio_conf));

    gpio_conf.mode         = GPIO_MODE_INPUT;
    gpio_conf.pin_bit_mask = (0x1ULL << busy);
    ESP_ERROR_CHECK_WITHOUT_ABORT(gpio_config(&gpio_conf));

    set_rst_1();
}

void CustomLcdDisplay::spi_port_init() {
    int              mosi     = lcd_spi_data.mosi;
    int              scl      = lcd_spi_data.scl;
    int              spi_host = lcd_spi_data.spi_host;
    esp_err_t        ret;
    spi_bus_config_t buscfg = {};
    buscfg.miso_io_num      = -1;
    buscfg.mosi_io_num      = mosi;
    buscfg.sclk_io_num      = scl;
    buscfg.quadwp_io_num    = -1;
    buscfg.quadhd_io_num    = -1;
    buscfg.max_transfer_sz  = Width * Height;

    spi_device_interface_config_t devcfg = {};
    devcfg.spics_io_num                  = -1;
    devcfg.clock_speed_hz                = 40 * 1000 * 1000; // Clock out at 10 MHz
    devcfg.mode                          = 0;                // SPI mode 0
    devcfg.queue_size                    = 7;                // We want to be able to queue 7 transactions at a time

    ret = spi_bus_initialize((spi_host_device_t) spi_host, &buscfg, SPI_DMA_CH_AUTO);
    ESP_ERROR_CHECK(ret);
    ret = spi_bus_add_device((spi_host_device_t) spi_host, &devcfg, &spi);
    ESP_ERROR_CHECK(ret);
}

void CustomLcdDisplay::read_busy() {
    int busy = lcd_spi_data.busy;
    while (gpio_get_level((gpio_num_t) busy) == 1) {
        vTaskDelay(pdMS_TO_TICKS(5)); // LOW: idle, HIGH: busy
    }
}

void CustomLcdDisplay::SPI_SendByte(uint8_t data) {
    esp_err_t         ret;
    spi_transaction_t t;
    memset(&t, 0, sizeof(t));
    t.length    = 8;
    t.tx_buffer = &data;
    ret         = spi_device_polling_transmit(spi, &t); // Transmit!
    assert(ret == ESP_OK);                              // Should have had no issues.
}

void CustomLcdDisplay::EPD_SendData(uint8_t data) {
    set_dc_1();
    set_cs_0();
    SPI_SendByte(data);
    set_cs_1();
}

void CustomLcdDisplay::EPD_SendCommand(uint8_t command) {
    set_dc_0();
    set_cs_0();
    SPI_SendByte(command);
    set_cs_1();
}

void CustomLcdDisplay::writeBytes(uint8_t *buffer, int len) {
    set_dc_1();
    set_cs_0();
    esp_err_t         ret;
    spi_transaction_t t;
    memset(&t, 0, sizeof(t));
    t.length    = 8 * len;
    t.tx_buffer = buffer;
    ret         = spi_device_polling_transmit(spi, &t); // Transmit!
    assert(ret == ESP_OK);
    set_cs_1();
}

void CustomLcdDisplay::writeBytes(const uint8_t *buffer, int len) {
    set_dc_1();
    set_cs_0();
    esp_err_t         ret;
    spi_transaction_t t;
    memset(&t, 0, sizeof(t));
    t.length    = 8 * len;
    t.tx_buffer = buffer;
    ret         = spi_device_polling_transmit(spi, &t); // Transmit!
    assert(ret == ESP_OK);
    set_cs_1();
}

void CustomLcdDisplay::EPD_SetWindows(uint16_t Xstart, uint16_t Ystart, uint16_t Xend, uint16_t Yend) {
    EPD_SendCommand(0x44); // SET_RAM_X_ADDRESS_START_END_POSITION
    EPD_SendData((Xstart >> 3) & 0xFF);
    EPD_SendData((Xend >> 3) & 0xFF);

    EPD_SendCommand(0x45); // SET_RAM_Y_ADDRESS_START_END_POSITION
    EPD_SendData(Ystart & 0xFF);
    EPD_SendData((Ystart >> 8) & 0xFF);
    EPD_SendData(Yend & 0xFF);
    EPD_SendData((Yend >> 8) & 0xFF);
}

void CustomLcdDisplay::EPD_SetCursor(uint16_t Xstart, uint16_t Ystart) {
    EPD_SendCommand(0x4E); // SET_RAM_X_ADDRESS_COUNTER
    EPD_SendData(Xstart & 0xFF);

    EPD_SendCommand(0x4F); // SET_RAM_Y_ADDRESS_COUNTER
    EPD_SendData(Ystart & 0xFF);
    EPD_SendData((Ystart >> 8) & 0xFF);
}

void CustomLcdDisplay::EPD_SetLut(const uint8_t *lut) {
    EPD_SendCommand(0x32);
    writeBytes(lut, 153);
    read_busy();

    EPD_SendCommand(0x3f);
    EPD_SendData(lut[153]);

    EPD_SendCommand(0x03);
    EPD_SendData(lut[154]);

    EPD_SendCommand(0x04);
    EPD_SendData(lut[155]);
    EPD_SendData(lut[156]);
    EPD_SendData(lut[157]);

    EPD_SendCommand(0x2c);
    EPD_SendData(lut[158]);
}

void CustomLcdDisplay::EPD_TurnOnDisplay() {
    EPD_SendCommand(0x22);
    EPD_SendData(0xc7);
    EPD_SendCommand(0x20);
    read_busy();
}

void CustomLcdDisplay::EPD_TurnOnDisplayPart() {
    EPD_SendCommand(0x22);
    EPD_SendData(0xcf);
    EPD_SendCommand(0x20);
    read_busy();
}

void CustomLcdDisplay::EPD_Init() {
    set_rst_1();
    vTaskDelay(pdMS_TO_TICKS(50));
    set_rst_0();
    vTaskDelay(pdMS_TO_TICKS(20));
    set_rst_1();
    vTaskDelay(pdMS_TO_TICKS(50));

    read_busy();
    EPD_SendCommand(0x12); // SWRESET
    read_busy();

    EPD_SendCommand(0x01); // Driver output control
    EPD_SendData(0xC7);
    EPD_SendData(0x00);
    EPD_SendData(0x01);

    EPD_SendCommand(0x11); // data entry mode
    EPD_SendData(0x01);

    EPD_SetWindows(0, Width - 1, Height - 1, 0);

    EPD_SendCommand(0x3C); // BorderWavefrom
    EPD_SendData(0x01);

    EPD_SendCommand(0x18);
    EPD_SendData(0x80);

    EPD_SendCommand(0x22); // Load Temperature and waveform setting.
    EPD_SendData(0XB1);
    EPD_SendCommand(0x20);

    EPD_SetCursor(0, Height - 1);
    read_busy();

    EPD_SetLut(WF_Full_1IN54);
}

void CustomLcdDisplay::EPD_Clear() {
    int buffer_len = lcd_spi_data.buffer_len;
    memset(buffer, 0xff, buffer_len);
}

void CustomLcdDisplay::EPD_Display() {
    int buffer_len = lcd_spi_data.buffer_len;
    EPD_SendCommand(0x24);
    assert(buffer);
    writeBytes(buffer, buffer_len);
    EPD_TurnOnDisplay();
}

void CustomLcdDisplay::EPD_DisplayPartBaseImage() {
    int buffer_len = lcd_spi_data.buffer_len;
    EPD_SendCommand(0x24);
    assert(buffer);
    writeBytes(buffer, buffer_len);
    EPD_SendCommand(0x26);
    writeBytes(buffer, buffer_len);
    EPD_TurnOnDisplay();
}

void CustomLcdDisplay::EPD_Init_Partial() {
    set_rst_1();
    vTaskDelay(pdMS_TO_TICKS(50));
    set_rst_0();
    vTaskDelay(pdMS_TO_TICKS(20));
    set_rst_1();
    vTaskDelay(pdMS_TO_TICKS(50));

    read_busy();

    EPD_SetLut(WF_PARTIAL_1IN54_0);

    EPD_SendCommand(0x37);
    EPD_SendData(0x00);
    EPD_SendData(0x00);
    EPD_SendData(0x00);
    EPD_SendData(0x00);
    EPD_SendData(0x00);
    EPD_SendData(0x40);
    EPD_SendData(0x00);
    EPD_SendData(0x00);
    EPD_SendData(0x00);
    EPD_SendData(0x00);

    EPD_SendCommand(0x3C); // BorderWavefrom
    EPD_SendData(0x80);

    EPD_SendCommand(0x22);
    EPD_SendData(0xc0);
    EPD_SendCommand(0x20);
    read_busy();
}

void CustomLcdDisplay::EPD_DisplayPart() {
    EPD_SendCommand(0x24);
    assert(buffer);
    writeBytes(buffer, 5000);
    EPD_TurnOnDisplayPart();
}

void CustomLcdDisplay::ShowStandbyLogo() {
    if (shell_mode_ || emoji_image_ == nullptr || chat_active_) {
        return;
    }
    if (chat_text_visible_) {
        PlaceChatLayout(true);
        return;
    }
    DisplayLockGuard lock(this);
    if (chat_panel_ != nullptr) {
        lv_obj_add_flag(chat_panel_, LV_OBJ_FLAG_HIDDEN);
    }
    if (gif_controller_) {
        gif_controller_->Stop();
        gif_controller_.reset();
    }
    lv_image_set_src(emoji_image_, &arena_standby_logo);
    lv_image_set_pivot(emoji_image_, arena_standby_logo.header.w / 2, arena_standby_logo.header.h / 2);
    lv_image_set_scale(emoji_image_, 256);
    lv_obj_center(emoji_image_);
    if (emoji_label_ != nullptr) {
        lv_obj_add_flag(emoji_label_, LV_OBJ_FLAG_HIDDEN);
    }
    int status_h = 24;
    if (status_bar_ != nullptr) {
        lv_obj_update_layout(status_bar_);
        int measured = lv_obj_get_height(status_bar_);
        if (measured > status_h) {
            status_h = measured;
        }
    }
    if (emoji_box_ != nullptr) {
        lv_obj_set_size(emoji_box_, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
        /* 中心点下移半个状态栏高度，logo 落在头部菜单以下区域的正中。 */
        lv_obj_align(emoji_box_, LV_ALIGN_CENTER, 0, status_h / 2);
        lv_obj_add_flag(emoji_box_, LV_OBJ_FLAG_OVERFLOW_VISIBLE);
        lv_obj_remove_flag(emoji_box_, LV_OBJ_FLAG_HIDDEN);
    }
    lv_obj_remove_flag(emoji_image_, LV_OBJ_FLAG_HIDDEN);
}

/* 一行大约 9 个汉字。整段一次贴上并滚到末尾时，屏幕只剩最后 4 行，而且会从半行切开。 */
namespace {

constexpr int kLinesPerPage = 4;
constexpr int kLineSpace = -6;
constexpr int kReadMsPerChar = 320;

size_t NextUtf8(const char* text, size_t len, size_t index, uint32_t* codepoint) {
    if (index >= len) {
        *codepoint = 0;
        return index;
    }
    const auto lead = static_cast<unsigned char>(text[index]);
    size_t width = 1;
    uint32_t value = lead;
    if (lead < 0x80) {
        value = lead;
    } else if ((lead & 0xE0) == 0xC0 && index + 1 < len) {
        width = 2;
        value = ((lead & 0x1F) << 6) | (static_cast<unsigned char>(text[index + 1]) & 0x3F);
    } else if ((lead & 0xF0) == 0xE0 && index + 2 < len) {
        width = 3;
        value = ((lead & 0x0F) << 12) |
                ((static_cast<unsigned char>(text[index + 1]) & 0x3F) << 6) |
                (static_cast<unsigned char>(text[index + 2]) & 0x3F);
    } else if ((lead & 0xF8) == 0xF0 && index + 3 < len) {
        width = 4;
        value = ((lead & 0x07) << 18) |
                ((static_cast<unsigned char>(text[index + 1]) & 0x3F) << 12) |
                ((static_cast<unsigned char>(text[index + 2]) & 0x3F) << 6) |
                (static_cast<unsigned char>(text[index + 3]) & 0x3F);
    }
    *codepoint = value;
    return index + width;
}

int CountCodepoints(const std::string& text) {
    int count = 0;
    const size_t len = text.size();
    size_t index = 0;
    while (index < len) {
        if (text[index] == '\n' || text[index] == '\r') {
            ++index;
            continue;
        }
        uint32_t codepoint = 0;
        index = NextUtf8(text.c_str(), len, index, &codepoint);
        if (codepoint != 0) {
            ++count;
        }
    }
    return count;
}

int GlyphWidth(const lv_font_t* font, uint32_t codepoint) {
    if (font == nullptr) {
        return codepoint < 0x80 ? 10 : 20;
    }
    const uint16_t measured = lv_font_get_glyph_width(font, codepoint, 0);
    if (measured > 0) {
        return measured;
    }
    return codepoint < 0x80 ? font->line_height / 2 : font->line_height;
}

}  // namespace

void CustomLcdDisplay::StopChatPages() {
    if (chat_page_timer_ != nullptr) {
        lv_timer_delete(chat_page_timer_);
        chat_page_timer_ = nullptr;
    }
}

void CustomLcdDisplay::ShowChatPage(int page) {
    if (chat_pages_.empty() || chat_message_label_ == nullptr) {
        return;
    }
    if (page < 0) {
        page = 0;
    }
    if (page >= static_cast<int>(chat_pages_.size())) {
        page = static_cast<int>(chat_pages_.size()) - 1;
    }
    chat_page_ = page;
    DisplayLockGuard lock(this);
    lv_label_set_text(chat_message_label_, chat_pages_[page].c_str());
    if (bottom_bar_ != nullptr) {
        lv_obj_scroll_to_y(bottom_bar_, 0, LV_ANIM_OFF);
    }
}

std::vector<std::string> CustomLcdDisplay::PaginateChat(const char* content) {
    std::vector<std::string> pages;
    if (content == nullptr || content[0] == '\0') {
        return pages;
    }
    const lv_font_t* font =
        chat_message_label_ != nullptr ? lv_obj_get_style_text_font(chat_message_label_, LV_PART_MAIN) : nullptr;
    int max_width = Width - 16;
    if (max_width < 40) {
        max_width = 40;
    }

    std::vector<std::string> lines;
    std::string line;
    int used = 0;
    const size_t len = std::strlen(content);
    size_t index = 0;
    while (index < len) {
        if (content[index] == '\n') {
            lines.push_back(line);
            line.clear();
            used = 0;
            ++index;
            continue;
        }
        if (content[index] == '\r') {
            ++index;
            continue;
        }
        uint32_t codepoint = 0;
        const size_t start = index;
        index = NextUtf8(content, len, index, &codepoint);
        const int glyph = GlyphWidth(font, codepoint);
        if (!line.empty() && used + glyph > max_width) {
            lines.push_back(line);
            line.clear();
            used = 0;
        }
        line.append(content + start, index - start);
        used += glyph;
    }
    if (!line.empty()) {
        lines.push_back(line);
    }
    if (lines.empty()) {
        lines.push_back(content);
    }

    for (size_t begin = 0; begin < lines.size(); begin += kLinesPerPage) {
        std::string page;
        const size_t end = std::min(lines.size(), begin + static_cast<size_t>(kLinesPerPage));
        for (size_t row = begin; row < end; ++row) {
            if (row > begin) {
                page += '\n';
            }
            page += lines[row];
        }
        pages.push_back(page);
    }
    return pages;
}

void CustomLcdDisplay::PlaceChatLayout(bool has_text) {
    if (!has_text) {
        chat_text_visible_ = false;
        ShowStandbyLogo();
        return;
    }
    chat_text_visible_ = true;
    if (emoji_image_ == nullptr || bottom_bar_ == nullptr || chat_message_label_ == nullptr) {
        return;
    }
    DisplayLockGuard lock(this);
    if (gif_controller_) {
        gif_controller_->Stop();
        gif_controller_.reset();
    }
    lv_image_set_src(emoji_image_, &arena_standby_logo);
    /* 播报时字标只留一窄条，支点放在顶端，缩小后的图不会伸进正文。 */
    constexpr int kLogoHeight = 36;
    const int src_h = arena_standby_logo.header.h > 0 ? arena_standby_logo.header.h : 125;
    lv_image_set_pivot(emoji_image_, arena_standby_logo.header.w / 2, 0);
    lv_image_set_scale(emoji_image_, (kLogoHeight * 256) / src_h);
    if (emoji_label_ != nullptr) {
        lv_obj_add_flag(emoji_label_, LV_OBJ_FLAG_HIDDEN);
    }
    int status_h = 24;
    if (status_bar_ != nullptr) {
        lv_obj_update_layout(status_bar_);
        int measured = lv_obj_get_height(status_bar_);
        if (measured > status_h) {
            status_h = measured;
        }
        lv_obj_set_style_bg_opa(status_bar_, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(status_bar_, lv_color_white(), 0);
        lv_obj_move_foreground(status_bar_);
    }
    if (top_bar_ != nullptr) {
        lv_obj_move_foreground(top_bar_);
    }
    if (emoji_box_ != nullptr) {
        lv_obj_set_size(emoji_box_, LV_PCT(100), kLogoHeight);
        lv_obj_align(emoji_box_, LV_ALIGN_TOP_MID, 0, status_h);
        lv_obj_remove_flag(emoji_box_, LV_OBJ_FLAG_OVERFLOW_VISIBLE);
        lv_obj_remove_flag(emoji_box_, LV_OBJ_FLAG_HIDDEN);
    }
    lv_obj_align(emoji_image_, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_remove_flag(emoji_image_, LV_OBJ_FLAG_HIDDEN);

    int text_h = Height - status_h - kLogoHeight;
    if (text_h < 40) {
        text_h = 40;
    }
    lv_obj_set_width(bottom_bar_, LV_PCT(100));
    lv_obj_set_height(bottom_bar_, text_h);
    lv_obj_set_style_bg_color(bottom_bar_, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(bottom_bar_, LV_OPA_COVER, 0);
    lv_obj_align(bottom_bar_, LV_ALIGN_BOTTOM_MID, 0, 0);
    /* 行距收紧，顶部留一点空，避免第一行被字标压住。 */
    lv_obj_set_style_pad_top(bottom_bar_, 6, 0);
    lv_obj_set_style_pad_bottom(bottom_bar_, 2, 0);
    lv_obj_set_style_pad_left(bottom_bar_, 4, 0);
    lv_obj_set_style_pad_right(bottom_bar_, 4, 0);
    lv_obj_set_style_text_line_space(chat_message_label_, kLineSpace, 0);
    lv_obj_set_style_text_align(chat_message_label_, LV_TEXT_ALIGN_LEFT, 0);
    lv_obj_set_width(chat_message_label_, LV_PCT(100));
    lv_obj_align(chat_message_label_, LV_ALIGN_TOP_LEFT, 0, 0);
    lv_obj_move_foreground(bottom_bar_);
    if (status_bar_ != nullptr) {
        lv_obj_move_foreground(status_bar_);
    }
    if (top_bar_ != nullptr) {
        lv_obj_move_foreground(top_bar_);
    }
    lv_obj_update_layout(bottom_bar_);
    lv_obj_scroll_to_y(bottom_bar_, 0, LV_ANIM_OFF);
}

void CustomLcdDisplay::RenderChat() {
    std::string body;
    for (size_t i = 0; i < segments_.size(); ++i) {
        if (i > 0) {
            body += "\n=====\n";
        }
        body += segments_[i].text;
    }
    lv_label_set_text(chat_label_, body.c_str());
    lv_obj_update_layout(chat_panel_);
    lv_obj_scroll_to_y(chat_panel_,
                       lv_obj_get_scroll_y(chat_panel_) + lv_obj_get_scroll_bottom(chat_panel_),
                       LV_ANIM_OFF);
}

void CustomLcdDisplay::AppendSegment(const char* role, const char* content) {
    if (content == nullptr || content[0] == '\0' || chat_label_ == nullptr) {
        return;
    }
    const char* speaker = (role != nullptr && role[0] != '\0') ? role : "system";
    if (!segments_.empty() && segments_.back().text == "好的，请稍等，我先查询一下数据。" &&
        std::strcmp(speaker, "assistant") == 0) {
        segments_.back().text = content;
    } else {
        segments_.push_back(ChatSegment{speaker, content});
    }
    while (segments_.size() > 12) {
        segments_.erase(segments_.begin());
    }
    DisplayLockGuard lock(this);
    RenderChat();
}

void CustomLcdDisplay::EnterChatScreen() {
    if (chat_panel_ == nullptr) {
        return;
    }
    chat_active_ = true;
    DisplayLockGuard lock(this);
    if (gif_controller_) {
        gif_controller_->Stop();
        gif_controller_.reset();
    }
    if (emoji_box_ != nullptr) {
        lv_obj_add_flag(emoji_box_, LV_OBJ_FLAG_HIDDEN);
    }
    if (status_bar_ != nullptr) {
        lv_obj_add_flag(status_bar_, LV_OBJ_FLAG_HIDDEN);
    }
    if (top_bar_ != nullptr) {
        lv_obj_add_flag(top_bar_, LV_OBJ_FLAG_HIDDEN);
    }
    if (bottom_bar_ != nullptr) {
        lv_obj_add_flag(bottom_bar_, LV_OBJ_FLAG_HIDDEN);
    }
    lv_obj_remove_flag(chat_panel_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(chat_panel_);
}

void CustomLcdDisplay::ExitChatScreen() {
    chat_active_ = false;
    segments_.clear();
    if (chat_label_ != nullptr) {
        DisplayLockGuard lock(this);
        lv_label_set_text(chat_label_, "");
        lv_obj_add_flag(chat_panel_, LV_OBJ_FLAG_HIDDEN);
        if (status_bar_ != nullptr) {
            lv_obj_remove_flag(status_bar_, LV_OBJ_FLAG_HIDDEN);
        }
        if (top_bar_ != nullptr) {
            lv_obj_remove_flag(top_bar_, LV_OBJ_FLAG_HIDDEN);
        }
    }
    ShowStandbyLogo();
}

void CustomLcdDisplay::SetEmotion(const char* emotion) {
    if (shell_mode_ || chat_active_) {
        return;
    }
    if (emotion != nullptr && std::strcmp(emotion, "neutral") == 0) {
        ShowStandbyLogo();
        return;
    }
    LcdDisplay::SetEmotion(emotion);
}

void CustomLcdDisplay::SetStatus(const char* status) {
    /* 状态只改顶部一行。不把待机图整屏换成聊天页，避免空字体把程序打崩。 */
    LvglDisplay::SetStatus(status);
    if (status == nullptr) {
        return;
    }
    standby_ = std::strcmp(status, Lang::Strings::STANDBY) == 0;
}

void CustomLcdDisplay::SetChatMessage(const char* role, const char* content) {
    if (shell_mode_) {
        return;
    }
    if (content == nullptr || content[0] == '\0') {
        return;
    }
    /* 和小智原来的字幕一样：表情留着，只在下方写教练的话，不留用户自己的话。 */
    if (role != nullptr && std::strcmp(role, "user") == 0) {
        return;
    }
    StopChatPages();
    spoken_text_.clear();
    shown_page_text_.clear();
    page_codepoint_end_.clear();
    span_codepoint_end_.clear();
    span_audio_end_ms_.clear();
    audio_total_ms_ = 0;
    speech_clock_on_ = false;
    chat_pages_ = PaginateChat(content);
    chat_page_ = 0;
    const char* first = chat_pages_.empty() ? content : chat_pages_.front().c_str();
    LcdDisplay::SetChatMessage(role, first);
    PlaceChatLayout(true);
}

void CustomLcdDisplay::StartSpeechPages(int duration_ms) {
    StopChatPages();
    page_switch_ms_.clear();
    if (chat_pages_.size() <= 1) {
        return;
    }
    int total = 0;
    std::vector<int> weights;
    weights.reserve(chat_pages_.size());
    for (const std::string& page : chat_pages_) {
        int weight = CountCodepoints(page);
        if (weight < 1) {
            weight = 1;
        }
        weights.push_back(weight);
        total += weight;
    }
    if (duration_ms <= 0) {
        duration_ms = std::max(total, 1) * kReadMsPerChar;
    }
    int consumed = 0;
    for (int weight : weights) {
        page_switch_ms_.push_back(static_cast<int>((static_cast<int64_t>(duration_ms) * consumed) / total));
        consumed += weight;
    }
    if (chat_page_ != 0) {
        ShowChatPage(0);
    }
    speech_started_us_ = esp_timer_get_time();
    chat_page_timer_ = lv_timer_create(
        [](lv_timer_t* timer) {
            auto* self = static_cast<CustomLcdDisplay*>(lv_timer_get_user_data(timer));
            if (self == nullptr || self->page_switch_ms_.empty()) {
                return;
            }
            const int elapsed = static_cast<int>((esp_timer_get_time() - self->speech_started_us_) / 1000);
            int page = 0;
            for (size_t index = 0; index < self->page_switch_ms_.size(); ++index) {
                if (elapsed >= self->page_switch_ms_[index]) {
                    page = static_cast<int>(index);
                }
            }
            if (page != self->chat_page_) {
                self->ShowChatPage(page);
            }
            if (page + 1 >= static_cast<int>(self->page_switch_ms_.size())) {
                self->StopChatPages();
            }
        },
        100, this);
}

void CustomLcdDisplay::RebuildSpokenPages() {
    chat_pages_ = PaginateChat(spoken_text_.c_str());
    page_codepoint_end_.clear();
    int consumed = 0;
    for (const std::string& page : chat_pages_) {
        int weight = CountCodepoints(page);
        if (weight < 1) {
            weight = 1;
        }
        consumed += weight;
        page_codepoint_end_.push_back(consumed);
    }
}

void CustomLcdDisplay::AdvanceSpokenPage() {
    if (page_codepoint_end_.empty() || span_audio_end_ms_.empty()) {
        return;
    }
    int elapsed = static_cast<int>((esp_timer_get_time() - speech_started_us_) / 1000);
    if (elapsed < 0) {
        elapsed = 0;
    }
    if (elapsed > audio_total_ms_) {
        elapsed = audio_total_ms_;
    }
    int previous_cp = 0;
    int previous_ms = 0;
    int codepoint = span_codepoint_end_.back();
    for (size_t index = 0; index < span_audio_end_ms_.size(); ++index) {
        const int end_ms = span_audio_end_ms_[index];
        const int end_cp = span_codepoint_end_[index];
        if (elapsed <= end_ms) {
            const int span_ms = std::max(end_ms - previous_ms, 1);
            const int into = std::max(elapsed - previous_ms, 0);
            codepoint = previous_cp + (end_cp - previous_cp) * into / span_ms;
            break;
        }
        previous_cp = end_cp;
        previous_ms = end_ms;
    }
    int page = static_cast<int>(page_codepoint_end_.size()) - 1;
    for (size_t index = 0; index < page_codepoint_end_.size(); ++index) {
        if (codepoint < page_codepoint_end_[index]) {
            page = static_cast<int>(index);
            break;
        }
    }
    if (page < 0 || chat_pages_.empty()) {
        return;
    }
    if (page != chat_page_ || chat_pages_[page] != shown_page_text_) {
        ShowChatPage(page);
        shown_page_text_ = chat_pages_[page];
    }
}

void CustomLcdDisplay::EnsureSpeechTimer() {
    if (chat_page_timer_ != nullptr) {
        return;
    }
    chat_page_timer_ = lv_timer_create(
        [](lv_timer_t* timer) {
            auto* self = static_cast<CustomLcdDisplay*>(lv_timer_get_user_data(timer));
            if (self != nullptr && self->speech_clock_on_) {
                self->AdvanceSpokenPage();
            }
        },
        100, this);
}

void CustomLcdDisplay::NoteSpokenSentence(const std::string& sentence, int duration_ms) {
    if (sentence.empty()) {
        return;
    }
    DisplayLockGuard lock(this);
    if (!spoken_text_.empty()) {
        spoken_text_ += "\n";
    }
    spoken_text_ += sentence;
    RebuildSpokenPages();
    const int chars = std::max(CountCodepoints(sentence), 1);
    int sentence_ms = duration_ms;
    if (sentence_ms <= 0) {
        sentence_ms = chars * kReadMsPerChar;
    }
    const int64_t now = esp_timer_get_time();
    if (!speech_clock_on_) {
        speech_started_us_ = now;
        audio_total_ms_ = 0;
        speech_clock_on_ = true;
    } else {
        const int elapsed = static_cast<int>((now - speech_started_us_) / 1000);
        if (elapsed > audio_total_ms_) {
            speech_started_us_ = now - static_cast<int64_t>(audio_total_ms_) * 1000;
        }
    }
    audio_total_ms_ += sentence_ms;
    int codepoint_end = page_codepoint_end_.empty() ? chars : page_codepoint_end_.back();
    span_codepoint_end_.push_back(codepoint_end);
    span_audio_end_ms_.push_back(audio_total_ms_);
    PlaceChatLayout(true);
    AdvanceSpokenPage();
    EnsureSpeechTimer();
}

void CustomLcdDisplay::AppendChatTurn(const char* role, const char* content) {
    SetChatMessage(role, content);
}

void CustomLcdDisplay::HoldChat() { ++hold_chat_; }

void CustomLcdDisplay::ReleaseChat() {
    if (hold_chat_ > 0) {
        --hold_chat_;
    }
}

void CustomLcdDisplay::RemoveChatMessage(const char* role, const char* content) {
    (void)role;
    (void)content;
}

void CustomLcdDisplay::ClearChatMessages() {
    if (hold_chat_ > 0) {
        return;
    }
    chat_text_visible_ = false;
    segments_.clear();
    StopChatPages();
    chat_pages_.clear();
    spoken_text_.clear();
    shown_page_text_.clear();
    page_codepoint_end_.clear();
    span_codepoint_end_.clear();
    span_audio_end_ms_.clear();
    audio_total_ms_ = 0;
    speech_clock_on_ = false;
    chat_page_ = 0;
    LcdDisplay::ClearChatMessages();
    ShowStandbyLogo();
}

void CustomLcdDisplay::SetupUI() {
    LcdDisplay::SetupUI();

    {
        DisplayLockGuard lock(this);
        chat_panel_ = lv_obj_create(lv_screen_active());
        lv_obj_set_size(chat_panel_, LV_HOR_RES, LV_VER_RES);
        lv_obj_set_pos(chat_panel_, 0, 0);
        lv_obj_set_style_bg_color(chat_panel_, lv_color_white(), 0);
        lv_obj_set_style_bg_opa(chat_panel_, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(chat_panel_, 0, 0);
        lv_obj_set_style_radius(chat_panel_, 0, 0);
        lv_obj_set_style_pad_all(chat_panel_, 4, 0);
        lv_obj_set_scrollbar_mode(chat_panel_, LV_SCROLLBAR_MODE_OFF);
        lv_obj_add_flag(chat_panel_, LV_OBJ_FLAG_HIDDEN);

        chat_label_ = lv_label_create(chat_panel_);
        lv_obj_set_width(chat_label_, LV_PCT(100));
        lv_label_set_long_mode(chat_label_, LV_LABEL_LONG_WRAP);
        lv_obj_set_style_text_color(chat_label_, lv_color_black(), 0);
        lv_obj_set_style_text_font(chat_label_,
                                   lv_obj_get_style_text_font(lv_screen_active(), LV_PART_MAIN), 0);
        lv_label_set_text(chat_label_, "");

        shell_panel_ = lv_obj_create(lv_screen_active());
        lv_obj_set_size(shell_panel_, LV_HOR_RES, LV_VER_RES);
        lv_obj_set_pos(shell_panel_, 0, 0);
        lv_obj_set_style_bg_color(shell_panel_, lv_color_white(), 0);
        lv_obj_set_style_bg_opa(shell_panel_, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(shell_panel_, 0, 0);
        lv_obj_set_style_radius(shell_panel_, 0, 0);
        lv_obj_set_style_pad_all(shell_panel_, 0, 0);
        lv_obj_set_scrollbar_mode(shell_panel_, LV_SCROLLBAR_MODE_OFF);
        lv_obj_add_flag(shell_panel_, LV_OBJ_FLAG_HIDDEN);

        shell_content_ = lv_obj_create(shell_panel_);
        lv_obj_set_size(shell_content_, LV_HOR_RES, LV_VER_RES);
        lv_obj_set_pos(shell_content_, 0, 0);
        lv_obj_set_style_bg_color(shell_content_, lv_color_white(), 0);
        lv_obj_set_style_bg_opa(shell_content_, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(shell_content_, 0, 0);
        lv_obj_set_style_radius(shell_content_, 0, 0);
        lv_obj_set_style_pad_all(shell_content_, 0, 0);
        lv_obj_set_scrollbar_mode(shell_content_, LV_SCROLLBAR_MODE_OFF);
        lv_obj_add_flag(shell_content_, LV_OBJ_FLAG_HIDDEN);

        shell_image_ = lv_image_create(shell_panel_);
        lv_image_set_src(shell_image_, &ian_home_logo);
        lv_obj_align(shell_image_, LV_ALIGN_CENTER, 0, 0);
        lv_obj_add_flag(shell_image_, LV_OBJ_FLAG_HIDDEN);

        shell_label_ = lv_label_create(shell_panel_);
        lv_obj_set_width(shell_label_, LV_PCT(100));
        lv_label_set_long_mode(shell_label_, LV_LABEL_LONG_WRAP);
        lv_obj_set_style_text_color(shell_label_, lv_color_black(), 0);
        lv_obj_set_style_pad_all(shell_label_, 8, 0);
        lv_obj_set_style_text_font(shell_label_,
                                   lv_obj_get_style_text_font(lv_screen_active(), LV_PART_MAIN), 0);
        lv_label_set_text(shell_label_, "");

        shell_chart_ = lv_line_create(shell_panel_);
        lv_obj_set_style_line_width(shell_chart_, 2, 0);
        lv_obj_set_style_line_color(shell_chart_, lv_color_black(), 0);
        lv_obj_set_style_line_rounded(shell_chart_, true, 0);
        lv_obj_add_flag(shell_chart_, LV_OBJ_FLAG_HIDDEN);
    }

    SwimShell::Get().Attach(this);
    /* 等 Assets 刷完主题字体后再进首页，避免 SetupUI 阶段旧 font 指针在刷新时 MMU 崩。 */
    ShowStandbyLogo();
}

void CustomLcdDisplay::SetTheme(Theme* theme) {
    LcdDisplay::SetTheme(theme);
    {
        DisplayLockGuard lock(this);
        const lv_font_t* font = lv_obj_get_style_text_font(lv_screen_active(), LV_PART_MAIN);
        if (font != nullptr) {
            if (shell_label_ != nullptr) {
                lv_obj_set_style_text_font(shell_label_, font, 0);
            }
            if (chat_label_ != nullptr) {
                lv_obj_set_style_text_font(chat_label_, font, 0);
            }
        }
    }
    if (!SwimShell::Get().IsActive()) {
        SwimShell::Get().ShowHome();
    } else {
        SwimShell::Get().Refresh();
    }
}

void CustomLcdDisplay::EnterShellMode() {
    DisplayLockGuard lock(this);
    shell_mode_ = true;
    if (status_bar_ != nullptr) {
        lv_obj_add_flag(status_bar_, LV_OBJ_FLAG_HIDDEN);
    }
    if (chat_panel_ != nullptr) {
        lv_obj_add_flag(chat_panel_, LV_OBJ_FLAG_HIDDEN);
    }
    if (shell_panel_ != nullptr) {
        lv_obj_remove_flag(shell_panel_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_move_foreground(shell_panel_);
    }
}

void CustomLcdDisplay::ExitShellMode() {
    DisplayLockGuard lock(this);
    shell_mode_ = false;
    if (shell_panel_ != nullptr) {
        lv_obj_add_flag(shell_panel_, LV_OBJ_FLAG_HIDDEN);
    }
    if (status_bar_ != nullptr) {
        lv_obj_remove_flag(status_bar_, LV_OBJ_FLAG_HIDDEN);
    }
}

const lv_font_t* CustomLcdDisplay::ShellFont() const {
    return lv_obj_get_style_text_font(lv_screen_active(), LV_PART_MAIN);
}

const lv_font_t* CustomLcdDisplay::ShellTitleFont() const {
    /* 与设计稿一致：标题与正文字号相同（约 20），仅加粗区分。 */
    return ShellFont();
}

void CustomLcdDisplay::ShellBare(lv_obj_t* obj) {
    if (obj == nullptr) {
        return;
    }
    lv_obj_remove_style_all(obj);
    lv_obj_set_scrollbar_mode(obj, LV_SCROLLBAR_MODE_OFF);
    lv_obj_set_style_pad_all(obj, 0, 0);
    lv_obj_set_style_border_width(obj, 0, 0);
    lv_obj_set_style_radius(obj, 0, 0);
    lv_obj_set_style_bg_opa(obj, LV_OPA_TRANSP, 0);
}

void CustomLcdDisplay::HideShellWidgets() {
    if (shell_content_ != nullptr) {
        lv_obj_clean(shell_content_);
        lv_obj_add_flag(shell_content_, LV_OBJ_FLAG_HIDDEN);
    }
    if (shell_label_ != nullptr) {
        lv_obj_add_flag(shell_label_, LV_OBJ_FLAG_HIDDEN);
    }
    if (shell_image_ != nullptr) {
        lv_obj_add_flag(shell_image_, LV_OBJ_FLAG_HIDDEN);
    }
    if (shell_chart_ != nullptr) {
        lv_obj_add_flag(shell_chart_, LV_OBJ_FLAG_HIDDEN);
    }
}

void CustomLcdDisplay::PrepareShellSurface(bool white_bg) {
    shell_mode_ = true;
    if (status_bar_ != nullptr) {
        lv_obj_add_flag(status_bar_, LV_OBJ_FLAG_HIDDEN);
    }
    if (chat_panel_ != nullptr) {
        lv_obj_add_flag(chat_panel_, LV_OBJ_FLAG_HIDDEN);
    }
    if (shell_panel_ == nullptr) {
        return;
    }
    lv_obj_remove_flag(shell_panel_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(shell_panel_);
    lv_obj_set_style_bg_color(shell_panel_, white_bg ? lv_color_white() : lv_color_black(), 0);
    lv_obj_set_style_pad_all(shell_panel_, 0, 0);
    HideShellWidgets();
}

lv_obj_t* CustomLcdDisplay::ShellBeginContent(int pad_all, int pad_row) {
    if (shell_content_ == nullptr) {
        return nullptr;
    }
    ShellBare(shell_content_);
    lv_obj_set_size(shell_content_, LV_HOR_RES, LV_VER_RES);
    lv_obj_set_pos(shell_content_, 0, 0);
    lv_obj_set_style_bg_color(shell_content_, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(shell_content_, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(shell_content_, pad_all, 0);
    lv_obj_set_style_pad_row(shell_content_, pad_row, 0);
    lv_obj_set_flex_flow(shell_content_, LV_FLEX_FLOW_COLUMN);
    lv_obj_remove_flag(shell_content_, LV_OBJ_FLAG_HIDDEN);
    return shell_content_;
}

lv_obj_t* CustomLcdDisplay::ShellBoldLabel(lv_obj_t* parent, const char* text, const lv_font_t* font,
                                          lv_color_t color, int wrap_width) {
    lv_obj_t* wrap = lv_obj_create(parent);
    ShellBare(wrap);
    /* set_pos 子节点不参与 SIZE_CONTENT，需按文字实测定宽高，否则标题行对齐会漂。 */
    lv_point_t sz = {};
    if (font != nullptr && text != nullptr && text[0] != '\0') {
        lv_text_get_size(&sz, text, font, 0, 0, wrap_width > 0 ? wrap_width : LV_COORD_MAX, LV_TEXT_FLAG_NONE);
    }
    const int fallback_h = (font != nullptr && font->line_height > 0) ? font->line_height : 28;
    const int text_h = sz.y > 0 ? static_cast<int>(sz.y) : fallback_h;
    const int text_w = sz.x > 0 ? static_cast<int>(sz.x) + 1 : 1;

    if (wrap_width > 0) {
        lv_obj_set_width(wrap, wrap_width);
        lv_obj_set_height(wrap, LV_SIZE_CONTENT);
    } else {
        lv_obj_set_size(wrap, text_w, text_h);
    }

    auto make = [&](int dx) {
        lv_obj_t* lab = lv_label_create(wrap);
        lv_label_set_text(lab, text != nullptr ? text : "");
        if (font != nullptr) {
            lv_obj_set_style_text_font(lab, font, 0);
        }
        lv_obj_set_style_text_color(lab, color, 0);
        if (wrap_width > 0) {
            lv_obj_set_width(lab, wrap_width);
            lv_label_set_long_mode(lab, LV_LABEL_LONG_WRAP);
            /* 换行布局下用 translate 做 1px 粗体，避免 set_pos 脱离流式排版 */
            if (dx != 0) {
                lv_obj_set_style_translate_x(lab, dx, 0);
            }
        } else {
            lv_obj_set_size(lab, text_w, text_h);
            lv_obj_set_pos(lab, dx, 0);
        }
        return lab;
    };
    make(0);
    make(1); /* 水平错位 1px，墨水屏上近似粗体 */
    return wrap;
}

void CustomLcdDisplay::ShellAddTitleHeader(lv_obj_t* root, const char* title, const char* repeat_badge) {
    /* 公用标题栏。设计：行高≈字线高、竖条 3×23、gap 5；
     * 竖条底边对齐文字基线；repeat_badge 如「3次」黑底白字贴标题右。 */
    const lv_font_t* title_font = ShellTitleFont();
    const lv_font_t* body_font = ShellFont();
    constexpr int kBarW = 3;
    constexpr int kBarH = 23;
    constexpr int kGap = 5;
    const int line_h = (title_font != nullptr && title_font->line_height > 0) ? title_font->line_height : 29;
    const int descent = (title_font != nullptr && title_font->base_line > 0) ? title_font->base_line : 3;
    int ink_bottom = line_h - descent;
    if (ink_bottom < kBarH) {
        ink_bottom = kBarH;
    }
    const int row_h = line_h > 29 ? line_h : 29;

    lv_obj_t* header = lv_obj_create(root);
    ShellBare(header);
    lv_obj_set_width(header, 200);
    lv_obj_set_height(header, LV_SIZE_CONTENT);
    lv_obj_set_style_pad_top(header, 12, 0);
    lv_obj_set_style_pad_left(header, 18, 0);
    lv_obj_set_style_pad_right(header, 18, 0);
    lv_obj_set_style_pad_row(header, 5, 0);
    lv_obj_set_flex_flow(header, LV_FLEX_FLOW_COLUMN);

    lv_obj_t* title_row = lv_obj_create(header);
    ShellBare(title_row);
    lv_obj_set_size(title_row, 164, row_h);
    lv_obj_set_layout(title_row, LV_LAYOUT_NONE);

    lv_obj_t* bar = lv_obj_create(title_row);
    ShellBare(bar);
    lv_obj_set_size(bar, kBarW, kBarH);
    lv_obj_set_pos(bar, 0, ink_bottom - kBarH);
    lv_obj_set_style_bg_color(bar, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);

    lv_obj_t* title_lab = ShellBoldLabel(title_row, title != nullptr ? title : "", title_font, lv_color_black());
    lv_obj_set_pos(title_lab, kBarW + kGap, 0);

    if (repeat_badge != nullptr && repeat_badge[0] != '\0') {
        lv_coord_t title_w = lv_obj_get_width(title_lab);
        if (title_w <= 0 && title_font != nullptr) {
            lv_point_t sz = {};
            lv_text_get_size(&sz, title != nullptr ? title : "", title_font, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
            title_w = sz.x + 1;
        }
        lv_obj_t* badge = lv_obj_create(title_row);
        ShellBare(badge);
        lv_obj_set_style_bg_color(badge, lv_color_black(), 0);
        lv_obj_set_style_bg_opa(badge, LV_OPA_COVER, 0);
        lv_obj_set_style_radius(badge, 8, 0);
        lv_obj_set_style_pad_hor(badge, 6, 0);
        lv_obj_set_style_pad_ver(badge, 2, 0);
        lv_obj_set_height(badge, LV_SIZE_CONTENT);
        lv_obj_set_width(badge, LV_SIZE_CONTENT);
        lv_obj_t* badge_lab = lv_label_create(badge);
        lv_label_set_text(badge_lab, repeat_badge);
        if (body_font != nullptr) {
            lv_obj_set_style_text_font(badge_lab, body_font, 0);
        }
        lv_obj_set_style_text_color(badge_lab, lv_color_white(), 0);
        lv_obj_set_pos(badge, kBarW + kGap + title_w + 6, ink_bottom - 22);
    }

    lv_obj_t* rule = lv_obj_create(header);
    ShellBare(rule);
    lv_obj_set_size(rule, 164, 1);
    lv_obj_set_style_bg_color(rule, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(rule, LV_OPA_COVER, 0);
}

void CustomLcdDisplay::ShowShellHome() {
    DisplayLockGuard lock(this);
    PrepareShellSurface(false);
    if (shell_image_ != nullptr) {
        lv_image_set_src(shell_image_, &ian_home_logo);
        lv_obj_align(shell_image_, LV_ALIGN_CENTER, 0, 0);
        lv_obj_remove_flag(shell_image_, LV_OBJ_FLAG_HIDDEN);
        lv_obj_move_foreground(shell_image_);
    }
    /* 烧录/启动后墨水屏常残留「正在初始化」：强制整屏失效，走一次全量 flush。 */
    if (display_ != nullptr) {
        lv_obj_invalidate(lv_display_get_screen_active(display_));
    }
}

void CustomLcdDisplay::ShowShellMenu(int focus) {
    /* 1:1 JaFM8：pad18 gap10，卡片高48、圆角9；文案 18/700 → 正文字号 + 双层错位加粗。 */
    DisplayLockGuard lock(this);
    PrepareShellSurface(true);
    lv_obj_t* root = ShellBeginContent(18, 10);
    if (root == nullptr) {
        return;
    }
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    static const char* kItems[] = {"单次分析", "趋势分析", "综合建议"};
    const lv_font_t* font = ShellFont();
    for (int i = 0; i < 3; ++i) {
        const bool sel = (i == focus);
        lv_obj_t* card = lv_obj_create(root);
        ShellBare(card);
        lv_obj_set_size(card, 164, 48);
        lv_obj_set_style_radius(card, 9, 0);
        lv_obj_set_style_border_width(card, sel ? 0 : 2, 0);
        lv_obj_set_style_border_color(card, lv_color_black(), 0);
        lv_obj_set_style_bg_color(card, sel ? lv_color_black() : lv_color_white(), 0);
        lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
        lv_obj_add_flag(card, LV_OBJ_FLAG_OVERFLOW_VISIBLE);
        lv_obj_set_layout(card, LV_LAYOUT_NONE);

        lv_obj_t* lab = ShellBoldLabel(card, kItems[i], font, sel ? lv_color_white() : lv_color_black());
        lv_obj_align(lab, LV_ALIGN_CENTER, 0, 0);
    }
}

void CustomLcdDisplay::ShowShellSessions(const std::vector<SessionListItem>& items, int focus, int window,
                                         const std::string& empty_hint) {
    /* 适配 20px 字体：一屏两张加高卡（164x78），结构仍对齐 KCLJQ 两行+状态 icon。 */
    DisplayLockGuard lock(this);
    PrepareShellSurface(true);
    lv_obj_t* root = ShellBeginContent(16, 12);
    if (root == nullptr) {
        return;
    }
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    const lv_font_t* font = ShellFont();

    if (items.empty()) {
        lv_obj_t* lab = lv_label_create(root);
        lv_label_set_text(lab, empty_hint.empty() ? "暂无场次" : empty_hint.c_str());
        if (font != nullptr) {
            lv_obj_set_style_text_font(lab, font, 0);
        }
        lv_obj_set_style_text_color(lab, lv_color_black(), 0);
        return;
    }

    constexpr int kVisible = 2;
    constexpr int kCardH = 78;
    constexpr int kRowH = 28;
    const int n = static_cast<int>(items.size());
    const int end = std::min(n, window + kVisible);
    for (int i = window; i < end; ++i) {
        const auto& row = items[i];
        const bool sel = (i == focus);
        const lv_color_t fg = sel ? lv_color_white() : lv_color_black();
        const lv_color_t bg = sel ? lv_color_black() : lv_color_white();

        lv_obj_t* card = lv_obj_create(root);
        ShellBare(card);
        lv_obj_set_size(card, 168, kCardH);
        lv_obj_set_style_radius(card, 9, 0);
        lv_obj_set_style_border_width(card, sel ? 0 : 2, 0);
        lv_obj_set_style_border_color(card, lv_color_black(), 0);
        lv_obj_set_style_bg_color(card, bg, 0);
        lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
        lv_obj_set_style_clip_corner(card, true, 0);
        lv_obj_set_style_pad_ver(card, 10, 0);
        lv_obj_set_style_pad_hor(card, 10, 0);
        lv_obj_set_style_pad_row(card, 8, 0);
        lv_obj_set_flex_flow(card, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(card, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

        lv_obj_t* top = lv_obj_create(card);
        ShellBare(top);
        lv_obj_set_size(top, 148, kRowH);
        lv_obj_set_flex_flow(top, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(top, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

        lv_obj_t* date = lv_label_create(top);
        lv_label_set_text(date, row.date.c_str());
        if (font != nullptr) {
            lv_obj_set_style_text_font(date, font, 0);
        }
        lv_obj_set_style_text_color(date, fg, 0);

        const bool done = row.can_open || row.status == "succeeded";
        const bool analyzing = row.status == "analyzing";
        if (done || analyzing) {
            lv_obj_t* icon = lv_image_create(top);
            if (done) {
                lv_image_set_src(icon, sel ? &icon_done_white : &icon_done_black);
            } else {
                lv_image_set_src(icon, sel ? &icon_analyzing_white : &icon_analyzing_black);
            }
            lv_obj_set_size(icon, 14, 14);
        }

        lv_obj_t* bottom = lv_obj_create(card);
        ShellBare(bottom);
        lv_obj_set_size(bottom, 148, kRowH);
        lv_obj_set_flex_flow(bottom, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(bottom, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

        /* 距离字段加粗；场次列表不展示 SWOLF。 */
        ShellBoldLabel(bottom, row.distance_text.c_str(), font, fg);
    }
}

void CustomLcdDisplay::ShowShellTrends(const std::vector<TrendListItem>& items, int focus,
                                       const std::string& empty_hint) {
    /* 1:1 BSrAu：pad18 gap7，九宫格每格圆角9。 */
    DisplayLockGuard lock(this);
    PrepareShellSurface(true);
    lv_obj_t* root = ShellBeginContent(18, 7);
    if (root == nullptr) {
        return;
    }
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    const lv_font_t* font = ShellFont();

    if (items.empty()) {
        lv_obj_t* lab = lv_label_create(root);
        lv_label_set_text(lab, empty_hint.empty() ? "暂无跨度" : empty_hint.c_str());
        if (font != nullptr) {
            lv_obj_set_style_text_font(lab, font, 0);
        }
        lv_obj_set_style_text_color(lab, lv_color_black(), 0);
        return;
    }

    const int n = static_cast<int>(items.size());
    constexpr int kCell = 50;
    for (int row = 0; row < 3; ++row) {
        lv_obj_t* line = lv_obj_create(root);
        ShellBare(line);
        lv_obj_set_size(line, 164, kCell);
        lv_obj_set_style_pad_column(line, 7, 0);
        lv_obj_set_flex_flow(line, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(line, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

        for (int col = 0; col < 3; ++col) {
            const int idx = row * 3 + col;
            lv_obj_t* cell = lv_obj_create(line);
            ShellBare(cell);
            lv_obj_set_size(cell, kCell, kCell);
            if (idx >= n) {
                continue;
            }
            const bool sel = (idx == focus);
            lv_obj_set_style_radius(cell, 9, 0);
            lv_obj_set_style_border_width(cell, sel ? 0 : 2, 0);
            lv_obj_set_style_border_color(cell, lv_color_black(), 0);
            lv_obj_set_style_bg_color(cell, sel ? lv_color_black() : lv_color_white(), 0);
            lv_obj_set_style_bg_opa(cell, LV_OPA_COVER, 0);

            /* 九宫格用 W/M/Y：1w→1W，1m→1M，1y→1Y。 */
            std::string short_label = items[idx].span;
            if (short_label.size() >= 2) {
                const char u = static_cast<char>(std::toupper(static_cast<unsigned char>(short_label.back())));
                if (u == 'W' || u == 'M' || u == 'Y') {
                    short_label.back() = u;
                }
            }
            if (short_label.empty()) {
                short_label = items[idx].label;
            }
            lv_obj_t* lab = lv_label_create(cell);
            lv_label_set_text(lab, short_label.c_str());
            if (font != nullptr) {
                lv_obj_set_style_text_font(lab, font, 0);
            }
            lv_obj_set_style_text_color(lab, sel ? lv_color_white() : lv_color_black(), 0);
            lv_obj_align(lab, LV_ALIGN_CENTER, 0, 0);
        }
    }
}

std::vector<std::string> CustomLcdDisplay::PaginateShellAiText(const std::string& text, int max_width,
                                                              int max_lines) {
    /* 与详情 AI 行一致：宽 138、按字形测宽换行，再按 max_lines 切页。 */
    std::vector<std::string> pages;
    if (text.empty() || max_lines <= 0) {
        return pages;
    }
    if (max_width < 40) {
        max_width = 40;
    }
    const lv_font_t* font = ShellFont();
    std::vector<std::string> lines;
    std::string line;
    int used = 0;
    const size_t len = text.size();
    size_t index = 0;
    while (index < len) {
        if (text[index] == '\n') {
            lines.push_back(line);
            line.clear();
            used = 0;
            ++index;
            continue;
        }
        if (text[index] == '\r') {
            ++index;
            continue;
        }
        uint32_t codepoint = 0;
        const size_t start = index;
        index = NextUtf8(text.c_str(), len, index, &codepoint);
        const int glyph = GlyphWidth(font, codepoint);
        if (!line.empty() && used + glyph > max_width) {
            lines.push_back(line);
            line.clear();
            used = 0;
        }
        line.append(text, start, index - start);
        used += glyph;
    }
    if (!line.empty() || lines.empty()) {
        lines.push_back(line);
    }
    for (size_t begin = 0; begin < lines.size(); begin += static_cast<size_t>(max_lines)) {
        std::string page;
        const size_t end = std::min(lines.size(), begin + static_cast<size_t>(max_lines));
        for (size_t row = begin; row < end; ++row) {
            if (row > begin) {
                page += '\n';
            }
            page += lines[row];
        }
        if (!page.empty()) {
            pages.push_back(std::move(page));
        }
    }
    return pages;
}

void CustomLcdDisplay::ShowShellReportPage(const std::string& title,
                                           const std::vector<ReportPageMetric>& metrics,
                                           const std::vector<std::string>& notes, bool show_more) {
    /* 1:1 详情页：标题栏竖条+标题+分隔线；指标/AI说明；底部分页三角。 */
    DisplayLockGuard lock(this);
    PrepareShellSurface(true);
    lv_obj_t* root = ShellBeginContent(0, 0);
    if (root == nullptr) {
        return;
    }
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_START);
    const lv_font_t* font = ShellFont();

    ShellAddTitleHeader(root, title.c_str());

    /* 左对齐：标签 hug、数值紧跟其后吃剩余宽；不再整列冒号右齐（短标签会浪费空隙）。 */
    constexpr int kRowW = 164;
    constexpr int kGap = 4;
    constexpr int kMinValueW = 40;

    auto normalize_pace = [](std::string s) {
        /* 2分14秒/100米 或 2分14秒 → 2'14" */
        std::string out;
        out.reserve(s.size());
        for (size_t i = 0; i < s.size();) {
            if (i + 1 < s.size() && s[i] >= '0' && s[i] <= '9') {
                size_t j = i;
                while (j < s.size() && s[j] >= '0' && s[j] <= '9') {
                    ++j;
                }
                const std::string fen = "\xE5\x88\x86"; /* 分 */
                const std::string miao = "\xE7\xA7\x92"; /* 秒 */
                if (j + fen.size() <= s.size() && s.compare(j, fen.size(), fen) == 0) {
                    size_t k = j + fen.size();
                    size_t sec_end = k;
                    while (sec_end < s.size() && s[sec_end] >= '0' && s[sec_end] <= '9') {
                        ++sec_end;
                    }
                    if (sec_end > k && sec_end + miao.size() <= s.size() &&
                        s.compare(sec_end, miao.size(), miao) == 0) {
                        out.append(s, i, j - i);
                        out.push_back('\'');
                        std::string sec = s.substr(k, sec_end - k);
                        if (sec.size() == 1) {
                            out.push_back('0');
                        }
                        out.append(sec);
                        out.push_back('"');
                        i = sec_end + miao.size();
                        const std::string per100 = "/100\xE7\xB1\xB3"; /* /100米 */
                        if (i + per100.size() <= s.size() && s.compare(i, per100.size(), per100) == 0) {
                            i += per100.size();
                        }
                        continue;
                    }
                }
            }
            out.push_back(s[i]);
            ++i;
        }
        return out;
    };

    auto metric_label = [](const std::string& raw) {
        std::string label = raw;
        if (!label.empty() && label.find("：") == std::string::npos && label.find(':') == std::string::npos) {
            label += "：";
        }
        return label;
    };

    lv_obj_t* body = lv_obj_create(root);
    ShellBare(body);
    lv_obj_set_size(body, 200, 133);
    lv_obj_set_style_pad_top(body, 10, 0);
    lv_obj_set_style_pad_left(body, 18, 0);
    lv_obj_set_style_pad_right(body, 18, 0);
    lv_obj_set_style_pad_row(body, 2, 0);
    lv_obj_set_flex_flow(body, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(body, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
    lv_obj_remove_flag(body, LV_OBJ_FLAG_OVERFLOW_VISIBLE);

    for (const auto& m : metrics) {
        const std::string label = metric_label(m.label);
        int lab_w = 0;
        if (font != nullptr && !label.empty()) {
            lv_point_t sz = {};
            lv_text_get_size(&sz, label.c_str(), font, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
            lab_w = static_cast<int>(sz.x) + 3;
        }
        int value_w = kRowW - kGap - lab_w;
        if (value_w < kMinValueW) {
            value_w = kMinValueW;
        }

        lv_obj_t* row = lv_obj_create(body);
        ShellBare(row);
        lv_obj_set_width(row, kRowW);
        lv_obj_set_height(row, LV_SIZE_CONTENT);
        lv_obj_set_style_pad_column(row, kGap, 0);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
        lv_obj_remove_flag(row, LV_OBJ_FLAG_OVERFLOW_VISIBLE);

        ShellBoldLabel(row, label.c_str(), font, lv_color_black());

        lv_obj_t* val = lv_label_create(row);
        lv_obj_set_flex_grow(val, 1);
        lv_obj_set_width(val, value_w);
        lv_label_set_long_mode(val, LV_LABEL_LONG_WRAP);
        const std::string value = normalize_pace(m.value);
        lv_label_set_text(val, value.c_str());
        if (font != nullptr) {
            lv_obj_set_style_text_font(val, font, 0);
        }
        lv_obj_set_style_text_color(val, lv_color_black(), 0);
    }

    for (const auto& note : notes) {
        if (note.empty()) {
            continue;
        }
        /* BrnoO：gap6；图标框 20×22，AI标记 20×20 顶偏 2（底对齐框） */
        lv_obj_t* row = lv_obj_create(body);
        ShellBare(row);
        lv_obj_set_width(row, 164);
        lv_obj_set_height(row, LV_SIZE_CONTENT);
        lv_obj_set_style_pad_column(row, 6, 0);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
        lv_obj_remove_flag(row, LV_OBJ_FLAG_OVERFLOW_VISIBLE);

        lv_obj_t* icon_box = lv_obj_create(row);
        ShellBare(icon_box);
        lv_obj_set_size(icon_box, 20, 22);
        lv_obj_t* icon = lv_image_create(icon_box);
        lv_image_set_src(icon, &icon_ai);
        lv_obj_set_size(icon, 20, 20);
        lv_obj_set_pos(icon, 0, 2);

        lv_obj_t* lab = lv_label_create(row);
        lv_obj_set_flex_grow(lab, 1);
        lv_obj_set_width(lab, 138);
        lv_label_set_long_mode(lab, LV_LABEL_LONG_WRAP);
        const std::string note_text = normalize_pace(note);
        lv_label_set_text(lab, note_text.c_str());
        if (font != nullptr) {
            lv_obj_set_style_text_font(lab, font, 0);
        }
        lv_obj_set_style_text_color(lab, lv_color_black(), 0);
    }

    lv_obj_t* footer = lv_obj_create(root);
    ShellBare(footer);
    lv_obj_set_size(footer, 200, 20);
    if (show_more) {
        lv_obj_t* chev = lv_image_create(footer);
        lv_image_set_src(chev, &icon_chevron_down);
        lv_obj_align(chev, LV_ALIGN_CENTER, 0, 0);
    }
}

void CustomLcdDisplay::ShowShellText(const std::string& text, bool invert) {
    /* 一次性加锁：避免 EnterShellMode + 本函数嵌套锁死 LVGL。 */
    DisplayLockGuard lock(this);
    PrepareShellSurface(!invert);
    if (shell_label_ == nullptr) {
        return;
    }
    lv_obj_set_style_bg_color(shell_panel_, invert ? lv_color_black() : lv_color_white(), 0);
    lv_obj_set_style_pad_all(shell_panel_, 8, 0);
    lv_obj_set_style_text_color(shell_label_, invert ? lv_color_white() : lv_color_black(), 0);
    lv_obj_remove_flag(shell_label_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_pos(shell_label_, 0, 0);
    lv_obj_set_width(shell_label_, LV_PCT(100));
    lv_label_set_text(shell_label_, text.c_str());
}

void CustomLcdDisplay::ShowShellTrendStatus(bool analyzing, const std::string& span_text,
                                            const std::string& primary, const std::string& secondary) {
    /* sOxZo(分析中) / D1yOTx(无数据)：标题栏 + 居中图标 + 三行文案。
     * 设备仅约 20px 字，稿面 14/16/12 叠满会裁底行；收紧上边距/行距并略缩图标。 */
    DisplayLockGuard lock(this);
    PrepareShellSurface(true);
    lv_obj_t* root = ShellBeginContent(0, 0);
    if (root == nullptr) {
        return;
    }
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_START);
    const lv_font_t* font = ShellFont();

    ShellAddTitleHeader(root, analyzing ? "分析中" : "无数据");

    lv_obj_t* body = lv_obj_create(root);
    ShellBare(body);
    lv_obj_set_width(body, 200);
    lv_obj_set_flex_grow(body, 1);
    lv_obj_set_style_pad_top(body, 4, 0);
    lv_obj_set_style_pad_bottom(body, 6, 0);
    lv_obj_set_style_pad_left(body, 18, 0);
    lv_obj_set_style_pad_right(body, 18, 0);
    lv_obj_set_style_pad_row(body, -4, 0);
    lv_obj_set_flex_flow(body, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(body, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_add_flag(body, LV_OBJ_FLAG_OVERFLOW_VISIBLE);

    constexpr int kIcon = 52;
    lv_obj_t* icon_zone = lv_obj_create(body);
    ShellBare(icon_zone);
    lv_obj_set_size(icon_zone, 164, kIcon);
    lv_obj_set_flex_flow(icon_zone, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(icon_zone, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_t* icon = lv_image_create(icon_zone);
    lv_image_set_src(icon, analyzing ? &icon_trend_analyzing : &icon_trend_empty);
    lv_obj_set_size(icon, kIcon, kIcon);

    auto add_line = [&](const std::string& text, bool bold) {
        if (text.empty()) {
            return;
        }
        lv_obj_t* row = lv_obj_create(body);
        ShellBare(row);
        lv_obj_set_width(row, 164);
        lv_obj_set_height(row, LV_SIZE_CONTENT);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_add_flag(row, LV_OBJ_FLAG_OVERFLOW_VISIBLE);
        if (bold) {
            lv_obj_t* lab = ShellBoldLabel(row, text.c_str(), font, lv_color_black(), 164);
            /* 居中：粗体 wrap 占满行宽后由 text_align 居中 */
            for (uint32_t ci = 0; ci < lv_obj_get_child_count(lab); ++ci) {
                lv_obj_t* child = lv_obj_get_child(lab, ci);
                if (child == nullptr) {
                    continue;
                }
                lv_obj_set_style_text_align(child, LV_TEXT_ALIGN_CENTER, 0);
                lv_obj_set_style_text_line_space(child, -6, 0);
            }
        } else {
            lv_obj_t* lab = lv_label_create(row);
            lv_obj_set_width(lab, 164);
            lv_label_set_long_mode(lab, LV_LABEL_LONG_WRAP);
            lv_obj_set_style_text_align(lab, LV_TEXT_ALIGN_CENTER, 0);
            lv_obj_set_style_text_line_space(lab, -6, 0);
            lv_label_set_text(lab, text.c_str());
            if (font != nullptr) {
                lv_obj_set_style_text_font(lab, font, 0);
            }
            lv_obj_set_style_text_color(lab, lv_color_black(), 0);
        }
    };

    add_line(span_text, true);
    add_line(primary, true);
    add_line(secondary, false);
}

void CustomLcdDisplay::ShowShellChart(const std::string& title, const std::vector<float>& values,
                                      const std::string& note) {
    /* 对齐 uP9po：标题栏 + 164x56 折线（左右各 18）+ 下方 AI 解读 + 分页三角。 */
    DisplayLockGuard lock(this);
    PrepareShellSurface(true);
    lv_obj_t* root = ShellBeginContent(0, 0);
    if (root == nullptr || shell_chart_ == nullptr) {
        return;
    }
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_START);
    const lv_font_t* font = ShellFont();

    ShellAddTitleHeader(root, title.c_str());

    lv_obj_t* body = lv_obj_create(root);
    ShellBare(body);
    lv_obj_set_size(body, 200, 128);
    lv_obj_set_style_pad_top(body, 8, 0);
    lv_obj_set_style_pad_left(body, 18, 0);
    lv_obj_set_style_pad_right(body, 18, 0);
    lv_obj_set_style_pad_row(body, 6, 0);
    lv_obj_set_flex_flow(body, LV_FLEX_FLOW_COLUMN);

    /* 图表容器：仅作占位，折线画在 shell_panel 绝对坐标上。 */
    lv_obj_t* chart_box = lv_obj_create(body);
    ShellBare(chart_box);
    lv_obj_set_size(chart_box, 164, 56);
    lv_obj_set_style_border_width(chart_box, 0, 0);

    if (!note.empty()) {
        lv_obj_t* note_row = lv_obj_create(body);
        ShellBare(note_row);
        lv_obj_set_width(note_row, 164);
        lv_obj_set_height(note_row, LV_SIZE_CONTENT);
        lv_obj_set_style_pad_column(note_row, 6, 0);
        lv_obj_set_flex_flow(note_row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(note_row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
        lv_obj_remove_flag(note_row, LV_OBJ_FLAG_OVERFLOW_VISIBLE);

        lv_obj_t* icon_box = lv_obj_create(note_row);
        ShellBare(icon_box);
        lv_obj_set_size(icon_box, 20, 22);
        lv_obj_t* icon = lv_image_create(icon_box);
        lv_image_set_src(icon, &icon_ai);
        lv_obj_set_size(icon, 20, 20);
        lv_obj_set_pos(icon, 0, 2);

        lv_obj_t* lab = lv_label_create(note_row);
        lv_obj_set_flex_grow(lab, 1);
        lv_obj_set_width(lab, 138);
        lv_label_set_long_mode(lab, LV_LABEL_LONG_WRAP);
        lv_label_set_text(lab, note.c_str());
        if (font != nullptr) {
            lv_obj_set_style_text_font(lab, font, 0);
        }
        lv_obj_set_style_text_color(lab, lv_color_black(), 0);
    }

    lv_obj_t* footer = lv_obj_create(root);
    ShellBare(footer);
    lv_obj_set_size(footer, 200, 20);
    lv_obj_t* chev = lv_image_create(footer);
    lv_image_set_src(chev, &icon_chevron_down);
    lv_obj_align(chev, LV_ALIGN_CENTER, 0, 0);

    static lv_point_precise_t pts[8];
    const int n = std::min(static_cast<int>(values.size()), 8);
    if (n < 2) {
        lv_obj_add_flag(shell_chart_, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    float vmin = values[0];
    float vmax = values[0];
    for (int i = 0; i < n; ++i) {
        vmin = std::min(vmin, values[i]);
        vmax = std::max(vmax, values[i]);
    }
    const float span = (vmax > vmin) ? (vmax - vmin) : 1.0f;
    /* 内容区：顶 47+10=57，左右 18，高 56，宽 164。 */
    constexpr int kLeft = 18;
    constexpr int kTop = 57;
    constexpr int kW = 164;
    constexpr int kH = 56;
    for (int i = 0; i < n; ++i) {
        const float t = (values[i] - vmin) / span;
        pts[i].x = kLeft + (kW * i) / (n - 1);
        pts[i].y = kTop + static_cast<int>((1.0f - t) * (kH - 4)) + 2;
    }
    lv_obj_set_style_line_width(shell_chart_, 3, 0);
    lv_obj_set_style_line_color(shell_chart_, lv_color_black(), 0);
    lv_obj_set_style_line_rounded(shell_chart_, true, 0);
    lv_line_set_points(shell_chart_, pts, n);
    lv_obj_remove_flag(shell_chart_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(shell_chart_);
    (void)chart_box;
}

void CustomLcdDisplay::ShowShellAdvice(const std::string& status_text, const std::string& body_text,
                                       const char* cta_state) {
    /* Jtixc（无 CTA）/ NAKaD（分析中）/ OVLGN（完成）：顶栏 K11Uf 图 + 聆听；中部引导/档案。 */
    DisplayLockGuard lock(this);
    PrepareShellSurface(true);
    /* 设计 pad [12,18] gap 8 */
    lv_obj_t* root = ShellBeginContent(0, 0);
    if (root == nullptr) {
        return;
    }
    lv_obj_set_style_pad_top(root, 12, 0);
    lv_obj_set_style_pad_bottom(root, 12, 0);
    lv_obj_set_style_pad_left(root, 18, 0);
    lv_obj_set_style_pad_right(root, 18, 0);
    lv_obj_set_style_pad_row(root, 8, 0);
    const lv_font_t* font = ShellFont();
    lv_obj_set_flex_flow(root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_START);

    lv_obj_t* top = lv_obj_create(root);
    ShellBare(top);
    lv_obj_set_width(top, 164);
    lv_obj_set_height(top, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(top, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(top, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(top, 8, 0);

    lv_obj_t* logo = lv_image_create(top);
    lv_image_set_src(logo, &icon_ian_logo);
    lv_obj_set_size(logo, 69, 38);

    lv_obj_t* st = lv_label_create(top);
    /* 空串 = 无状态（勿默认「正在聆听」）；用空格占位避免布局塌掉 */
    lv_label_set_text(st, status_text.empty() ? " " : status_text.c_str());
    if (font != nullptr) {
        lv_obj_set_style_text_font(st, font, 0);
    }
    lv_obj_set_style_text_color(st, lv_color_black(), 0);

    /* hidden / none：首次无档案，不画按钮；analyzing / ready / idle：有档案才出 CTA */
    const char* state = cta_state != nullptr ? cta_state : "hidden";
    const bool show_cta =
        std::strcmp(state, "hidden") != 0 && std::strcmp(state, "none") != 0;

    /* 正文容器固定高度，避免长档案盖住底部 CTA（有 CTA≈86px，无 CTA≈120px） */
    lv_obj_t* body_box = lv_obj_create(root);
    ShellBare(body_box);
    lv_obj_set_width(body_box, 164);
    lv_obj_set_height(body_box, show_cta ? 86 : 120);
    lv_obj_set_style_clip_corner(body_box, true, 0);
    lv_obj_add_flag(body_box, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scroll_dir(body_box, LV_DIR_VER);

    lv_obj_t* body = lv_label_create(body_box);
    lv_obj_set_width(body, 164);
    lv_label_set_long_mode(body, LV_LABEL_LONG_WRAP);
    lv_label_set_text(body, body_text.c_str());
    if (font != nullptr) {
        lv_obj_set_style_text_font(body, font, 0);
    }
    lv_obj_set_style_text_color(body, lv_color_black(), 0);
    /* 修改档案说明偏长：再压行距，多挤出 1～2 行可见内容 */
    lv_obj_set_style_text_line_space(body, -8, 0);

    if (!show_cta) {
        return;
    }

    lv_obj_t* cta = lv_obj_create(root);
    ShellBare(cta);
    lv_obj_set_size(cta, 164, 36);
    lv_obj_set_style_bg_color(cta, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(cta, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(cta, 9, 0);
    lv_obj_set_flex_flow(cta, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(cta, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(cta, 8, 0);
    lv_obj_set_style_pad_hor(cta, 12, 0);

    lv_obj_t* cta_lab = lv_label_create(cta);
    lv_label_set_text(cta_lab, "建议训练计划");
    if (font != nullptr) {
        lv_obj_set_style_text_font(cta_lab, font, 0);
    }
    lv_obj_set_style_text_color(cta_lab, lv_color_white(), 0);

    if (std::strcmp(state, "analyzing") == 0 || std::strcmp(state, "ready") == 0) {
        lv_obj_t* icon = lv_image_create(cta);
        lv_image_set_src(icon, std::strcmp(state, "analyzing") == 0 ? &icon_analyzing_white : &icon_done_white);
        lv_obj_set_size(icon, 14, 14);
    }
}

void CustomLcdDisplay::ShowShellAdviceHub(const std::string& status_text, int focus, bool plan_ready,
                                          bool plan_analyzing) {
    /* imRzc：Logo+状态；四按钮 个人档案 / 修改档案 / 训练计划 / 修改生成计划。 */
    DisplayLockGuard lock(this);
    PrepareShellSurface(true);
    lv_obj_t* root = ShellBeginContent(0, 0);
    if (root == nullptr) {
        return;
    }
    /* 四键略压高度：顶 8 + 行距 4 + 按钮 30，保证 200 屏内完整。 */
    lv_obj_set_style_pad_top(root, 8, 0);
    lv_obj_set_style_pad_bottom(root, 8, 0);
    lv_obj_set_style_pad_left(root, 18, 0);
    lv_obj_set_style_pad_right(root, 18, 0);
    lv_obj_set_style_pad_row(root, 4, 0);
    const lv_font_t* font = ShellFont();
    lv_obj_set_flex_flow(root, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_START);

    lv_obj_t* top = lv_obj_create(root);
    ShellBare(top);
    lv_obj_set_width(top, 164);
    lv_obj_set_height(top, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(top, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(top, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(top, 8, 0);

    lv_obj_t* logo = lv_image_create(top);
    lv_image_set_src(logo, &icon_ian_logo);
    lv_obj_set_size(logo, 69, 38);

    lv_obj_t* st = lv_label_create(top);
    lv_label_set_text(st, status_text.empty() ? " " : status_text.c_str());
    if (font != nullptr) {
        lv_obj_set_style_text_font(st, font, 0);
    }
    lv_obj_set_style_text_color(st, lv_color_black(), 0);

    static const char* kLabels[] = {"个人档案", "修改档案", "训练计划", "修改/生成计划"};
    for (int i = 0; i < 4; ++i) {
        const bool sel = (i == focus);
        const lv_color_t fg = sel ? lv_color_white() : lv_color_black();
        const lv_color_t bg = sel ? lv_color_black() : lv_color_white();

        lv_obj_t* btn = lv_obj_create(root);
        ShellBare(btn);
        lv_obj_set_size(btn, 164, 30);
        lv_obj_set_style_radius(btn, 9, 0);
        lv_obj_set_style_border_width(btn, sel ? 0 : 2, 0);
        lv_obj_set_style_border_color(btn, lv_color_black(), 0);
        lv_obj_set_style_bg_color(btn, bg, 0);
        lv_obj_set_style_bg_opa(btn, LV_OPA_COVER, 0);
        lv_obj_set_flex_flow(btn, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(btn, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_pad_column(btn, 8, 0);
        lv_obj_set_style_pad_hor(btn, 12, 0);

        lv_obj_t* lab = lv_label_create(btn);
        lv_label_set_text(lab, kLabels[i]);
        if (font != nullptr) {
            lv_obj_set_style_text_font(lab, font, 0);
        }
        lv_obj_set_style_text_color(lab, fg, 0);

        /* 训练计划：有可打开计划显示 ✓；修改/生成计划：生成中显示转圈 */
        if (i == 2 && plan_ready) {
            lv_obj_t* icon = lv_image_create(btn);
            lv_image_set_src(icon, sel ? &icon_done_white : &icon_done_black);
            lv_obj_set_size(icon, 14, 14);
        } else if (i == 3 && plan_analyzing) {
            lv_obj_t* icon = lv_image_create(btn);
            lv_image_set_src(icon, sel ? &icon_analyzing_white : &icon_analyzing_black);
            lv_obj_set_size(icon, 14, 14);
        }
    }
}

void CustomLcdDisplay::ShowShellPlanPage(const std::string& title, const std::string& repeat_badge,
                                         const std::vector<ReportPageMetric>& metrics, bool show_more) {
    /* FuWw8 / BPJ3a / AoZhj：标题栏（可带次数徽章）+ 字段行 + 底三角。 */
    DisplayLockGuard lock(this);
    PrepareShellSurface(true);
    lv_obj_t* root = ShellBeginContent(0, 0);
    if (root == nullptr) {
        return;
    }
    lv_obj_set_flex_align(root, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_START);
    const lv_font_t* font = ShellFont();

    ShellAddTitleHeader(root, title.c_str(), repeat_badge.empty() ? nullptr : repeat_badge.c_str());

    /* 左对齐：标签 hug、数值紧跟其后；「注释」仍上下排。 */
    constexpr int kRowW = 164;
    constexpr int kGap = 4;
    constexpr int kMinValueW = 40;

    auto is_stacked_metric = [](const std::string& label) {
        /* 长文案字段上下排：避免「注释：」右侧换行、标签下大片空白 */
        return label == "注释" || label.find("注释") == 0;
    };

    auto metric_label = [](const std::string& raw) {
        std::string label = raw;
        if (!label.empty() && label.find("：") == std::string::npos && label.find(':') == std::string::npos) {
            label += "：";
        }
        return label;
    };

    lv_obj_t* body = lv_obj_create(root);
    ShellBare(body);
    lv_obj_set_size(body, 200, show_more ? 133 : 153);
    lv_obj_set_style_pad_top(body, 10, 0);
    lv_obj_set_style_pad_left(body, 18, 0);
    lv_obj_set_style_pad_right(body, 18, 0);
    lv_obj_set_style_pad_row(body, 2, 0);
    lv_obj_set_flex_flow(body, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(body, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
    /* 超高内容裁切；完整字段靠服务端拆页 + B 键下翻 */
    lv_obj_remove_flag(body, LV_OBJ_FLAG_OVERFLOW_VISIBLE);
    lv_obj_set_style_clip_corner(body, true, 0);

    for (const auto& m : metrics) {
        const std::string label = metric_label(m.label);
        const bool stacked = is_stacked_metric(m.label);
        lv_obj_t* row = lv_obj_create(body);
        ShellBare(row);
        lv_obj_set_width(row, kRowW);
        lv_obj_set_height(row, LV_SIZE_CONTENT);
        if (stacked) {
            lv_obj_set_style_pad_row(row, 2, 0);
            lv_obj_set_flex_flow(row, LV_FLEX_FLOW_COLUMN);
            lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
            ShellBoldLabel(row, label.c_str(), font, lv_color_black(), kRowW);
            lv_obj_t* val = lv_label_create(row);
            lv_obj_set_width(val, kRowW);
            lv_label_set_long_mode(val, LV_LABEL_LONG_WRAP);
            lv_label_set_text(val, m.value.c_str());
            if (font != nullptr) {
                lv_obj_set_style_text_font(val, font, 0);
            }
            lv_obj_set_style_text_color(val, lv_color_black(), 0);
            continue;
        }

        int lab_w = 0;
        if (font != nullptr && !label.empty()) {
            lv_point_t sz = {};
            lv_text_get_size(&sz, label.c_str(), font, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
            lab_w = static_cast<int>(sz.x) + 3;
        }
        int value_w = kRowW - kGap - lab_w;
        if (value_w < kMinValueW) {
            value_w = kMinValueW;
        }

        lv_obj_set_style_pad_column(row, kGap, 0);
        lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
        lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

        ShellBoldLabel(row, label.c_str(), font, lv_color_black());

        const bool bold_value = (m.label == "距离" || m.label.find("距离") == 0 || m.label == "休息" ||
                                 m.label.find("休息") == 0);
        if (bold_value) {
            ShellBoldLabel(row, m.value.c_str(), font, lv_color_black(), value_w);
        } else {
            lv_obj_t* val = lv_label_create(row);
            lv_obj_set_flex_grow(val, 1);
            lv_obj_set_width(val, value_w);
            lv_label_set_long_mode(val, LV_LABEL_LONG_WRAP);
            lv_label_set_text(val, m.value.c_str());
            if (font != nullptr) {
                lv_obj_set_style_text_font(val, font, 0);
            }
            lv_obj_set_style_text_color(val, lv_color_black(), 0);
        }
    }

    if (show_more) {
        lv_obj_t* footer = lv_obj_create(root);
        ShellBare(footer);
        lv_obj_set_size(footer, 200, 20);
        lv_obj_t* chev = lv_image_create(footer);
        lv_image_set_src(chev, &icon_chevron_down);
        lv_obj_align(chev, LV_ALIGN_CENTER, 0, 0);
    }
}

void CustomLcdDisplay::EPD_DrawColorPixel(uint16_t x, uint16_t y, uint8_t color) {
    if (x >= Width || y >= Height) {
        ESP_LOGE("EPD", "Out of bounds pixel: (%d,%d)", x, y);
        return;
    }

    uint16_t index = y * 25 + (x >> 3);
    uint8_t  bit   = 7 - (x & 0x07);
    if (color == DRIVER_COLOR_WHITE) {
        buffer[index] |= (0x01 << bit);
    } else {
        buffer[index] &= ~(0x01 << bit);
    }
}
