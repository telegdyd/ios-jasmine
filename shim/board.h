#pragma once
/*
 * Per-board constants. build.sh passes -DBOARD_JASMINE (Xiaomi Mi A2, SDM660)
 * or -DBOARD_TOPAZ (Redmi Note 12 4G, SM6225). Both have Kryo 260 Silver
 * (no 16K granule) + Gold cores and GICv3 with the virtual timer on INTID 19.
 */

#if defined(BOARD_JASMINE)

#define BOARD_NAME		"jasmine"
/* ABL continuous splash (reserved-memory splash_region, simple-framebuffer in mainline) */
#define FB_BASE			0x9d400000UL
#define FB_W			1080
#define FB_H			2160
#define GICD_BASE		0x17a00000UL
#define GICR_BASE		0x17b00000UL
/* qcom,msm-imem@146bf000 restart_reason@65c (stock DT) */
#define IMEM_RESTART_REASON	0x146bf65cUL
#define PSHOLD			0x010ac000UL
/* qcom,msm-watchdog (stock DT): bark 11 s, pet 10 s if anyone left it on */
#define APSS_WDT_BASE		0x17817000UL
#define BOARD_HAS_CPUFREQ_HW	0
#define BOARD_HAS_UFS		0

#elif defined(BOARD_TOPAZ)

#define BOARD_NAME		"topaz"
#define FB_BASE			0x5c000000UL	/* reserved-memory cont_splash_region */
#define FB_W			1080
#define FB_H			2400
#define GICD_BASE		0x0f200000UL
#define GICR_BASE		0x0f300000UL
#define IMEM_RESTART_REASON	0x0c12565cUL	/* qcom,msm-imem@c125000 restart_reason@65c */
#define PSHOLD			0x0440b000UL
#define BOARD_HAS_CPUFREQ_HW	1
#define BOARD_HAS_UFS		1

#else
#error "define BOARD_JASMINE or BOARD_TOPAZ"
#endif

#define FB_STRIDE		(FB_W * 4)	/* a8r8g8b8, matches mainline simplefb */
