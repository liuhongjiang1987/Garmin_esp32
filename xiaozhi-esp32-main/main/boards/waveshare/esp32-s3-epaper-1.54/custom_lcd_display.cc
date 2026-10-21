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

#include <esp_timer.h>

#include <algorithm>
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
    if (emoji_image_ == nullptr || chat_active_) {
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
    if (chat_active_) {
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
    }

    ShowStandbyLogo();
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
