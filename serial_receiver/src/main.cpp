#include "simple_radio.h"
#include <driver/uart.h>
#include <freertos/FreeRTOS.h>
#include <freertos/message_buffer.h>
#include <freertos/task.h>

extern "C" void app_main() {
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 2 * 1024, 512, 0, NULL, 0));

    uart_config_t uart_config = {};
    uart_config.baud_rate = 921600;
    uart_config.data_bits = UART_DATA_8_BITS;
    uart_config.parity = UART_PARITY_DISABLE;
    uart_config.stop_bits = UART_STOP_BITS_1;
    uart_config.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
    uart_config.source_clk = UART_SCLK_DEFAULT;
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_0, &uart_config));

    auto msg_queue = xMessageBufferCreate(4096);

    SimpleRadio.begin(12);
    SimpleRadio.setIgnoreRepeatedMessages(false);

    SimpleRadio.setOnStringCallback([=](std::string str, PacketInfo info) {
        char buf[64];
        auto buf_len = snprintf(buf, sizeof(buf) - 1, "%02x%02x%02x%02x%02x%02x %.*s", info.addr[0], info.addr[1],
            info.addr[2], info.addr[3], info.addr[4], info.addr[5], str.size(), str.c_str());
        xMessageBufferSend(msg_queue, buf, buf_len, 0);
    });

    char in_buff[64];
    while (true) {
        auto rec_len = xMessageBufferReceive(msg_queue, in_buff, sizeof(in_buff), portMAX_DELAY);
        if (rec_len == 0) {
            continue;
        }

        if (memchr(in_buff, '\n', rec_len) != NULL) {
            continue;
        }

        in_buff[rec_len++] = '\n';
        uart_write_bytes(UART_NUM_0, in_buff, rec_len);
    }
}
