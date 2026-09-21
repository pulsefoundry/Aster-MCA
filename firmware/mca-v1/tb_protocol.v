`timescale 1ns/1ps

module tb_protocol;
    reg clk = 1'b0;
    reg [11:0] adc_data = 12'd2048;
    reg uart_rx_pin = 1'b1;
    wire uart_tx_pin;
    wire adc_pd;
    wire status_led;
    wire trig_out;

    top dut (
        .clk_10mhz(clk),
        .adc_data(adc_data),
        .uart_rx_pin(uart_rx_pin),
        .uart_tx_pin(uart_tx_pin),
        .adc_pd(adc_pd),
        .status_led(status_led),
        .trig_out(trig_out)
    );

    always #50 clk = ~clk; // 10 MHz

    wire [7:0] monitor_data;
    wire monitor_valid;
    wire monitor_error;
    uart_rx #(.CLKS_PER_BIT(10)) monitor (
        .clk(clk),
        .rst(dut.rst),
        .rx(uart_tx_pin),
        .data(monitor_data),
        .valid(monitor_valid),
        .framing_error(monitor_error)
    );

    reg [7:0] received [0:63];
    integer received_count = 0;
    always @(posedge clk) begin
        if (monitor_error)
            $fatal(1, "framing error in FPGA response");
        if (monitor_valid) begin
            received[received_count] <= monitor_data;
            received_count <= received_count + 1;
        end
    end

    task send_uart_byte;
        input [7:0] value;
        integer bit_number;
        begin
            @(negedge clk);
            uart_rx_pin <= 1'b0;
            repeat (10) @(negedge clk);
            for (bit_number = 0; bit_number < 8; bit_number = bit_number + 1) begin
                uart_rx_pin <= value[bit_number];
                repeat (10) @(negedge clk);
            end
            uart_rx_pin <= 1'b1;
            repeat (10) @(negedge clk);
        end
    endtask

    function [15:0] crc16_next;
        input [15:0] crc_in;
        input [7:0] byte_in;
        integer bit_number;
        reg [15:0] work;
        begin
            work = crc_in ^ {byte_in, 8'h00};
            for (bit_number = 0; bit_number < 8; bit_number = bit_number + 1)
                if (work[15])
                    work = (work << 1) ^ 16'h1021;
                else
                    work = work << 1;
            crc16_next = work;
        end
    endfunction

    integer i;
    reg [15:0] calculated_crc;
    initial begin
        wait(dut.rst === 1'b0);
        repeat (16) @(posedge clk);
        send_uart_byte(8'h49); // I

        wait(received_count == 26); // 8 header + 16 payload + 2 CRC
        repeat (4) @(posedge clk);

        if ({received[0], received[1], received[2], received[3]} != 32'h4d434131)
            $fatal(1, "bad response magic");
        if (received[4] != 8'h49 || received[5] != 8'h00)
            $fatal(1, "bad INFO response type/status");
        if (received[6] != 8'd16 || received[7] != 8'd0)
            $fatal(1, "bad INFO payload length");
        if (received[8] != 8'd1 || received[9] != 8'd3 || received[10] != 8'd12)
            $fatal(1, "bad INFO firmware/ADC fields");

        calculated_crc = 16'hffff;
        for (i = 0; i < 24; i = i + 1)
            calculated_crc = crc16_next(calculated_crc, received[i]);
        if ({received[25], received[24]} != calculated_crc)
            $fatal(1, "bad response CRC: got %04x expected %04x",
                {received[25], received[24]}, calculated_crc);

        $display("PASS: end-to-end UART INFO frame and CRC");
        $finish;
    end

    initial begin
        #500000;
        $fatal(1, "protocol simulation timeout");
    end
endmodule
