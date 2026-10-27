/*
 *  Copyright (C) 2002-2021  The DOSBox Team
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License along
 *  with this program; if not, write to the Free Software Foundation, Inc.,
 *  51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
 */

#include <cstdint>
#include <string>
#include <vector>

void DEBUG_SetupConsole(void);
void DEBUG_DrawScreen(void);
bool DEBUG_Breakpoint(void);
bool DEBUG_IntBreakpoint(uint8_t intNum);
void DEBUG_Enable(bool pressed);
void DEBUG_CheckExecuteBreakpoint(uint16_t seg, uint32_t off);
bool DEBUG_ExitLoop(void);
void DEBUG_RefreshPage(char scroll);
Bitu DEBUG_EnableDebugger(void);

#if C_DEBUG
bool DEBUG_AgentStep(bool over, bool* continued);
bool DEBUG_AgentResumeAfterTerminate(void);
bool DEBUG_AgentCanStartTarget(void);
uint64_t DEBUG_AgentEntryBreakpointSequence(void);
bool DEBUG_AgentCreateExecutionBreakpoint(uint16_t seg, uint32_t off, bool once, uintptr_t* handle);
bool DEBUG_AgentCreateMemoryBreakpoint(uint16_t seg, uint32_t off, bool protected_mode, bool linear, uintptr_t* handle);
bool DEBUG_AgentCreateLinearBreakpoint(uint32_t linear, bool once, uintptr_t* handle);
bool DEBUG_AgentCreateSelectorBreakpoint(uint16_t seg, uint32_t off, bool once, uintptr_t* handle);
bool DEBUG_AgentSetBreakpointCondition(uintptr_t handle, const char* condition);
bool DEBUG_AgentSetBreakpointHitLimit(uintptr_t handle, uint32_t limit);
bool DEBUG_AgentResolveAddress(bool linear, uint16_t seg, uint32_t off, uint64_t* linear_address, uint64_t* physical_address);

// The register values of a state.set_registers request.
struct DEBUG_AgentRegisterValues {
    uint32_t eax = 0, ebx = 0, ecx = 0, edx = 0;
    uint32_t esi = 0, edi = 0, ebp = 0, esp = 0;
    uint16_t cs = 0, ds = 0, es = 0, fs = 0, gs = 0, ss = 0;
    uint32_t instruction_pointer = 0;
    uint32_t flags = 0;
};

bool DEBUG_AgentSetRegisters(const DEBUG_AgentRegisterValues* registers);

// The coverage record, for the agent coverage methods.
struct DEBUG_AgentCoverageRange {
    uint64_t start = 0;
    uint64_t end = 0;
};

bool DEBUG_AgentCoverageStart(uint64_t start, uint64_t length);
bool DEBUG_AgentCoverageRead(std::vector<DEBUG_AgentCoverageRange>* ranges,
                             uint64_t* start, uint64_t* length,
                             uint64_t* covered, uint64_t* dropped);
bool DEBUG_AgentCoverageStop(uint64_t* covered);

// The file-I/O record, for the DOS file calls and the agent fileio methods.
struct DEBUG_AgentFileIoRecord {
    uint64_t sequence = 0;
    std::string event;
    std::string name;
    uint32_t handle = 0;
    uint32_t offset = 0;
    uint32_t count = 0;
};

bool DEBUG_AgentFileIoStart(const char* filename);
bool DEBUG_AgentFileIoRead(uint64_t cursor, bool has_cursor, uint32_t limit,
                            std::vector<DEBUG_AgentFileIoRecord>* records,
                            bool* has_next, uint64_t* next_cursor);
bool DEBUG_AgentFileIoStop(uint64_t* records);
bool DEBUG_AgentKeyText(const char* text,uint32_t* injected);
bool DEBUG_AgentKeyScan(uint32_t scan,uint32_t* injected);
bool DEBUG_AgentKeyScript(const char* filename,uint32_t* lines);
bool DEBUG_AgentKeyStop();
bool DEBUG_AgentInputStop();
bool DEBUG_AgentMouseMove(int x,int y);
bool DEBUG_AgentMouseButton(uint8_t button,bool down);
bool DEBUG_AgentMouseClick(uint8_t button);
bool DEBUG_AgentScreenText(const char* filename,uint32_t* rows,uint32_t* columns);
bool DEBUG_AgentScreenImage(const char* filename);
void DEBUG_InputRunTimers();

// The file-I/O record used by the DOS file calls.
class CDbgFileIo {
public:
    static bool Start(const char* filename);
    static void Stop();
    static bool IsActive();
    static void Record(const char* event, const char* name, uint16_t handle,
                        uint32_t offset, uint32_t count);
    static bool Read(uint64_t cursor, bool has_cursor, uint32_t limit,
                      std::vector<DEBUG_AgentFileIoRecord>* records,
                      bool* has_next, uint64_t* next_cursor);
    static std::string Status();
    static uint64_t GetRecords() { return records; }

private:
    static FILE* file;
    static std::string path;
    static uint64_t records;
    static uint64_t dropped;
    static std::vector<DEBUG_AgentFileIoRecord> list;
    static bool active;
};
bool DEBUG_AgentDeleteBreakpoint(uintptr_t handle);
uintptr_t DEBUG_AgentConsumeLastBreakpoint(void);
void DEBUG_AgentClearLastBreakpoint(void);
bool DEBUG_AgentBeginOutputCapture(void);
std::string DEBUG_AgentEndOutputCapture(void);
#if C_HEAVY_DEBUG
struct DEBUG_AgentTraceEvent {
    uint16_t cs = 0;
    uint32_t instruction_pointer = 0;
    uint32_t eax = 0;
    uint32_t ebx = 0;
    uint32_t ecx = 0;
    uint32_t edx = 0;
    uint32_t esi = 0;
    uint32_t edi = 0;
    uint32_t ebp = 0;
    uint32_t esp = 0;
    uint16_t ds = 0;
    uint16_t es = 0;
    uint16_t fs = 0;
    uint16_t gs = 0;
    uint16_t ss = 0;
    uint32_t flags = 0;
    std::string instruction;
    std::string analysis;
};
bool DEBUG_AgentStartTrace(uint32_t instruction_count);
bool DEBUG_AgentStopTrace(uint32_t* event_count);
bool DEBUG_AgentTraceIsActive(void);
void DEBUG_AgentCopyTraceEvents(std::vector<DEBUG_AgentTraceEvent>* events);
#endif
#endif

extern Bitu cycle_count;
extern Bitu debugCallback;

#ifdef C_HEAVY_DEBUG
bool DEBUG_HeavyIsBreakpoint(void);
void DEBUG_HeavyWriteLogInstruction(void);
#endif
