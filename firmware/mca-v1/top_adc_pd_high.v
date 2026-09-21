// Diagnostic wrapper.  It leaves the MCA logic unchanged but asserts the ADC
// power-down pin so we can see whether the external converter reacts.
module top_adc_pd_high (
    input  wire        clk_10mhz,
    input  wire [11:0] adc_data,
    input  wire        uart_rx_pin,
    output wire        uart_tx_pin,
    output wire        adc_pd,
    output wire        status_led,
    output wire        trig_out
);
    wire unused_adc_pd;

    top core (
        .clk_10mhz(clk_10mhz),
        .adc_data(adc_data),
        .uart_rx_pin(uart_rx_pin),
        .uart_tx_pin(uart_tx_pin),
        .adc_pd(unused_adc_pd),
        .status_led(status_led),
        .trig_out(trig_out)
    );

    assign adc_pd = 1'b1;
endmodule
