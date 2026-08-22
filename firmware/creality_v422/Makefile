# Makefile pour STM32F103 (Creality V4.2.2)
# Usage: make [all|clean|flash]

TOOLCHAIN_PREFIX ?= arm-none-eabi-
CC := $(TOOLCHAIN_PREFIX)gcc
OBJCOPY := $(TOOLCHAIN_PREFIX)objcopy
SIZE := $(TOOLCHAIN_PREFIX)size
AR := $(TOOLCHAIN_PREFIX)ar

# Répertoires
SRC_DIR = src
BUILD_DIR = build
OBJ_DIR = $(BUILD_DIR)/obj

# Fichiers
SRCS = $(wildcard $(SRC_DIR)/*.c)
OBJS = $(patsubst $(SRC_DIR)/%.c,$(OBJ_DIR)/%.o,$(SRCS))
ELF = $(BUILD_DIR)/firmware.elf
HEX = $(BUILD_DIR)/firmware.hex
BIN = $(BUILD_DIR)/firmware.bin
LD_SCRIPT = stm32f103_flash.ld

# Flags de compilation
ARCH_FLAGS = -mcpu=cortex-m3 -mthumb -msoft-float
WARN_FLAGS = -Wall -Wextra -pedantic -Wstrict-prototypes
OPT_FLAGS = -O2 -g3
CFLAGS = $(ARCH_FLAGS) $(WARN_FLAGS) $(OPT_FLAGS)
CFLAGS += -ffunction-sections -fdata-sections -fno-builtin
CFLAGS += -D STM32F103RB -D STM32F10X_MD

# Flags de linking
LDFLAGS = $(ARCH_FLAGS)
LDFLAGS += -Wl,--gc-sections -Wl,--build-id=none
LDFLAGS += -nostartfiles -T$(LD_SCRIPT)

# Couleurs pour l'affichage
RED = \033[0;31m
GREEN = \033[0;32m
YELLOW = \033[1;33m
BLUE = \033[0;34m
NC = \033[0m

.PHONY: all clean build help flash size info

all: build size

build: $(HEX) $(BIN)

$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR) $(OBJ_DIR)

$(OBJ_DIR)/%.o: $(SRC_DIR)/%.c | $(BUILD_DIR)
	@echo -e "$(BLUE)[CC]$(NC) $<"
	@$(CC) $(CFLAGS) -c $< -o $@

$(ELF): $(OBJS) $(LD_SCRIPT) | $(BUILD_DIR)
	@echo -e "$(BLUE)[LD]$(NC) $@"
	@$(CC) $(LDFLAGS) $(OBJS) -o $@

$(HEX): $(ELF)
	@echo -e "$(BLUE)[OBJCOPY]$(NC) $(HEX)"
	@$(OBJCOPY) -O ihex $(ELF) $(HEX)

$(BIN): $(ELF)
	@echo -e "$(BLUE)[OBJCOPY]$(NC) $(BIN)"
	@$(OBJCOPY) -O binary $(ELF) $(BIN)

size: $(ELF)
	@echo ""
	@echo -e "$(GREEN)=== Taille du firmware ===$(NC)"
	@$(SIZE) -d $(ELF)
	@echo -e "$(GREEN)=======================\n$(NC)"

info: $(HEX)
	@echo -e "$(GREEN)=== Informations firmware ===$(NC)"
	@echo "ELF:  $(ELF)"
	@echo "HEX:  $(HEX)"
	@echo "BIN:  $(BIN)"
	@echo "LD:   $(LD_SCRIPT)"
	@echo -e "$(GREEN)==========================\n$(NC)"

flash: $(HEX)
	@echo -e "$(YELLOW)Flashage en cours...$(NC)"
	@which st-flash > /dev/null 2>&1 || { echo -e "$(RED)Erreur: st-flash non trouvé$(NC)"; exit 1; }
	@st-flash write $(HEX) 0x08000000
	@echo -e "$(GREEN)✓ Flashage réussi$(NC)"

verify:
	@echo -e "$(BLUE)Vérification de la Creality...$(NC)"
	@which st-info > /dev/null 2>&1 || { echo -e "$(RED)Erreur: st-info non trouvé$(NC)"; exit 1; }
	@st-info --probe

clean:
	@echo -e "$(YELLOW)Nettoyage...$(NC)"
	@rm -rf $(BUILD_DIR)
	@echo -e "$(GREEN)✓ Nettoyé$(NC)"

help:
	@echo -e "$(GREEN)=== STM32F103 Firmware Build ===$(NC)"
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo -e "  $(BLUE)all$(NC)        - Compiler le firmware (défaut)"
	@echo -e "  $(BLUE)clean$(NC)      - Supprimer les fichiers compilés"
	@echo -e "  $(BLUE)size$(NC)       - Afficher la taille du firmware"
	@echo -e "  $(BLUE)info$(NC)       - Afficher les infos de compilation"
	@echo -e "  $(BLUE)flash$(NC)      - Flasher sur la Creality (nécessite ST-LINK)"
	@echo -e "  $(BLUE)verify$(NC)     - Vérifier la connexion ST-LINK"
	@echo -e "  $(BLUE)help$(NC)       - Afficher cette aide"
	@echo ""
	@echo "Variables:"
	@echo -e "  $(BLUE)TOOLCHAIN_PREFIX$(NC) - Préfixe du toolchain (défaut: arm-none-eabi-)"
	@echo -e "$(GREEN)================================$(NC)"
