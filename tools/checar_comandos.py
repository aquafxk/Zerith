"""Procura nomes de comandos duplicados entre os cogs (o que derruba o bot na inicialização)."""
import ast, sys, pathlib, collections

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
slash, prefix, groups = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)

def kw(call, key):
    for k in call.keywords:
        if k.arg == key:
            return k.value
    return None

def const(node):
    return node.value if isinstance(node, ast.Constant) else None

for path in sorted((root / "cogs").glob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    group_vars = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Attribute) and f.attr == "Group":
                name = const(kw(node.value, "name")) or (const(node.value.args[0]) if node.value.args else None)
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        group_vars.add(t.id)
                if name:
                    groups[name].append(path.name)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            owner, attr = dec.func.value, dec.func.attr
            owner_name = owner.id if isinstance(owner, ast.Name) else (owner.attr if isinstance(owner, ast.Attribute) else "")
            name = const(kw(dec, "name")) or node.name
            if attr == "command" and owner_name == "app_commands":
                slash[name].append(f"{path.name}:{node.lineno}")
            elif attr in ("command", "group") and owner_name == "commands":
                prefix[name].append(f"{path.name}:{node.lineno}")
                al = kw(dec, "aliases")
                if isinstance(al, (ast.List, ast.Tuple)):
                    for a in al.elts:
                        if const(a):
                            prefix[const(a)].append(f"{path.name}:{node.lineno} (alias)")
            elif attr == "hybrid_command" or (attr == "command" and owner_name == "commands"):
                pass

bad = False
for title, table in (("SLASH (nível raiz)", slash), ("PREFIXO (nome/alias)", prefix), ("GRUPOS", groups)):
    for name, where in sorted(table.items()):
        if len(where) > 1:
            bad = True
            print(f"❌ {title}: '{name}' definido {len(where)}x -> {', '.join(where)}")
for name in set(slash) & set(groups):
    bad = True
    print(f"❌ '{name}' é comando slash e grupo ao mesmo tempo: {slash[name]} / {groups[name]}")
print(f"slash raiz: {len(slash) + len(groups)} (limite do Discord: 100) | prefixo: {len(prefix)}")
print("RESULTADO:", "DUPLICIDADES ENCONTRADAS" if bad else "sem duplicidades")
sys.exit(1 if bad else 0)
