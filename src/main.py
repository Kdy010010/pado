import re
import sys

class ExtendedPadoTranspiler:
    def __init__(self):
        self.state = {
            "in_asm_block": False,
            "asm_lines": [],
            "indent_level": 0,
            "has_main": False,
            "output_lines": [],
            "headers": set(),
            "in_multiline_comment": False,
        }
        
    def indent(self):
        return "    " * self.state["indent_level"]

    def add_line(self, line):
        self.state["output_lines"].append(self.indent() + line)

    def generate_headers(self):
        header_lines = []
        # 예: stdio 모듈이 import된 경우만 포함
        if "stdio" in self.state["headers"]:
            header_lines.append("#include <stdio.h>")
        # freestanding 환경에서는 최소한의 헤더만 포함하도록 함.
        return header_lines

    def transpile(self, code):
        lines = code.splitlines()
        for line in lines:
            self.process_line(line)
        # OS용 엔트리 포인트 (_start) 추가 (main 함수가 있으면)
        if self.state["has_main"]:
            self.state["output_lines"].append("")
            self.state["output_lines"].append("// OS 엔트리 포인트 (_start)")
            self.state["output_lines"].append("void _start() {")
            self.state["output_lines"].append("    main();")
            self.state["output_lines"].append("    while(1) { }")
            self.state["output_lines"].append("}")
        header_code = "\n".join(self.generate_headers())
        return header_code + "\n" + "\n".join(self.state["output_lines"])

    def process_line(self, line):
        # 다중 줄 주석 처리 (/* ... */)
        if self.state["in_multiline_comment"]:
            if "*/" in line:
                self.state["in_multiline_comment"] = False
                line = line.split("*/", 1)[1]
            else:
                return
        if "/*" in line:
            before, sep, after = line.partition("/*")
            line = before
            if "*/" in after:
                # 한 줄 안에서 끝남
                line += after.split("*/", 1)[1]
            else:
                self.state["in_multiline_comment"] = True

        # 한 줄 주석 제거 (//)
        line = re.sub(r'//.*', '', line)

        stripped = line.strip()
        if stripped == "":
            return
        
        # import 구문 (모듈 포함)
        if stripped.startswith("import "):
            parts = stripped.split()
            if len(parts) >= 2:
                lib = parts[1]
                self.state["headers"].add(lib)
            return

        # asm 블록 처리
        if self.state["in_asm_block"]:
            if stripped == "}":
                asm_code = " ".join(self.state["asm_lines"])
                self.add_line(f'__asm__("{asm_code}");')
                self.state["in_asm_block"] = False
                self.state["asm_lines"] = []
            else:
                self.state["asm_lines"].append(stripped)
            return
        if stripped.startswith("asm {"):
            self.state["in_asm_block"] = True
            self.state["asm_lines"] = []
            return

        # 중괄호 블록에 따른 indent 처리
        if stripped.endswith("{"):
            transpiled = self.transpile_statement(stripped)
            self.add_line(transpiled)
            self.state["indent_level"] += 1
            return
        if stripped == "}":
            self.state["indent_level"] = max(0, self.state["indent_level"] - 1)
            return
        
        transpiled = self.transpile_statement(stripped)
        self.add_line(transpiled)

    def transpile_statement(self, stmt):
        # 함수 정의: fn funcName(params: type, ...) -> return_type {
        m = re.match(r'fn\s+(\w+)\s*\((.*?)\)\s*(?:->\s*(\w+))?\s*{', stmt)
        if m:
            func_name = m.group(1)
            if func_name == "main":
                self.state["has_main"] = True
            params = m.group(2)
            ret_type = m.group(3) if m.group(3) else "int"
            param_list = []
            if params.strip():
                for part in params.split(','):
                    part = part.strip()
                    if ":" in part:
                        name, typ = part.split(":", 1)
                        param_list.append(f"{typ.strip()} {name.strip()}")
                    else:
                        param_list.append(f"int {part.strip()}")
            param_str = ", ".join(param_list)
            return f"{ret_type} {func_name}({param_str}) " + "{"
        
        # 변수 선언: let 또는 var
        m = re.match(r'(let|var)\s+(\w+)\s*=\s*(.*);', stmt)
        if m:
            var_name = m.group(2)
            expr = m.group(3)
            # 간단하게 문자열 리터럴이면 char*, 아니면 int
            if re.match(r'^".*"$', expr):
                var_type = "char*"
            else:
                var_type = "int"
            return f"{var_type} {var_name} = {expr};"

        # if/else 구문
        if stmt.startswith("if") or stmt.startswith("else if") or stmt.startswith("else"):
            # 조건문의 괄호와 중괄호는 그대로 C와 유사한 문법 사용
            return stmt

        # while, for 구문
        if stmt.startswith("while") or stmt.startswith("for"):
            return stmt

        # return 문
        if stmt.startswith("return"):
            if not stmt.endswith(";"):
                stmt += ";"
            return stmt

        # print/println 처리
        if stmt.startswith("print(") or stmt.startswith("println("):
            return self.transform_print(stmt)

        # scanf 처리
        if stmt.startswith("scanf("):
            return self.transform_scanf(stmt)

        # 기본 문장: 세미콜론 자동 추가 (이미 세미콜론이 있으면 그대로)
        if not stmt.endswith(";"):
            stmt += ";"
        return stmt

    def transform_print(self, stmt):
        """
        print()와 println()을 C의 printf 함수 호출로 변환합니다.
        문자열 리터럴과 간단한 정수 표현을 지원합니다.
        """
        m = re.match(r'(print|println)\s*\((.*)\)\s*;', stmt)
        if m:
            func = m.group(1)
            content = m.group(2)
            args = self.split_args(content)
            format_str = ""
            other_args = []
            for arg in args:
                arg = arg.strip()
                if re.match(r'^".*"$', arg):
                    format_str += arg[1:-1]
                else:
                    format_str += "%d"
                    other_args.append(arg)
            if func == "println":
                format_str += "\\n"
            if other_args:
                return f'printf("{format_str}", {", ".join(other_args)});'
            else:
                return f'printf("{format_str}");'
        return stmt

    def transform_scanf(self, stmt):
        """
        scanf(buffer, max_length); 를 변환합니다.
        실제 구현은 BIOS 키보드 인터럽트나 다른 메커니즘을 사용해야 하나,
        여기서는 placeholder 코드로 주석 처리합니다.
        """
        m = re.match(r'scanf\s*\((.*)\)\s*;', stmt)
        if m:
            content = m.group(1)
            args = self.split_args(content)
            if len(args) >= 2:
                buffer_arg = args[0].strip()
                max_len = args[1].strip()
                code = f"// scanf: 입력을 받아 {buffer_arg}에 저장 (최대 {max_len} 바이트)\n"
                code += f"/* 실제 구현 필요: BIOS int 0x16 또는 기타 키보드 I/O 사용 */\n"
                code += f"{buffer_arg}[0] = '\\0';"
                return code
        return stmt

    def split_args(self, s):
        args = []
        current = ""
        in_quotes = False
        for char in s:
            if char == '"' and (not current or current[-1] != '\\'):
                in_quotes = not in_quotes
            if char == ',' and not in_quotes:
                args.append(current.strip())
                current = ""
            else:
                current += char
        if current.strip():
            args.append(current.strip())
        return args

def main():
    if len(sys.argv) < 2:
        print("Usage: python extended_pado_transpiler.py <source_file.pado>")
        sys.exit(1)
    source_file = sys.argv[1]
    try:
        with open(source_file, "r", encoding="utf-8") as f:
            pado_code = f.read()
    except FileNotFoundError:
        print(f"File not found: {source_file}")
        sys.exit(1)
    transpiler = ExtendedPadoTranspiler()
    c_code = transpiler.transpile(pado_code)
    output_file = source_file.rsplit(".", 1)[0] + ".c"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(c_code)
    print(f"Transpiled {source_file} to {output_file}")

if __name__ == "__main__":
    main()
