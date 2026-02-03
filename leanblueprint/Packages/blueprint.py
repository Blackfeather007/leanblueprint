"""
Package Lean blueprint

This depends on the depgraph plugin. This plugin has to be installed but then it is
used automatically.

Options:
* project: lean project path

* showmore: enable buttons showing or hiding proofs (this requires the showmore plugin).

You can also add options that will be passed to the dependency graph package.
"""
import json
import string
from pathlib import Path

from jinja2 import Template
from plasTeX import Command
from plasTeX.Logging import getLogger
from plasTeX.PackageResource import PackageCss, PackageTemplateDir, PackagePreCleanupCB
from plastexdepgraph.Packages.depgraph import item_kind, DepGraph

log = getLogger()

PKG_DIR = Path(__file__).parent
STATIC_DIR = Path(__file__).parent.parent/'static'


class home(Command):
    r"""\home{url}"""
    args = 'url:url'

    def invoke(self, tex):
        Command.invoke(self, tex)
        self.ownerDocument.userdata['project_home'] = self.attributes['url']
        return []


class github(Command):
    r"""\github{url}"""
    args = 'url:url'

    def invoke(self, tex):
        Command.invoke(self, tex)
        self.ownerDocument.userdata['project_github'] = self.attributes['url'].textContent.rstrip(
            '/')
        return []


class dochome(Command):
    r"""\dochome{url}"""
    args = 'url:url'

    def invoke(self, tex):
        Command.invoke(self, tex)
        self.ownerDocument.userdata['project_dochome'] = self.attributes['url'].textContent
        return []


class graphcolor(Command):
    r"""\graphcolor{node_type}{color}{color_descr}"""
    args = 'node_type:str color:str color_descr:str'

    def digest(self, tokens):
        Command.digest(self, tokens)
        attrs = self.attributes
        colors = self.ownerDocument.userdata['dep_graph']['colors']
        node_type = attrs['node_type']
        if node_type not in colors:
            log.warning(f'Unknown node type {node_type}')
        colors[node_type] = (attrs['color'].strip(), attrs['color_descr'].strip())


class leanok(Command):
    r"""\leanok"""

    def digest(self, tokens):
        Command.digest(self, tokens)
        self.parentNode.userdata['leanok'] = True


class notready(Command):
    r"""\notready"""

    def digest(self, tokens):
        Command.digest(self, tokens)
        self.parentNode.userdata['notready'] = True


class mathlibok(Command):
    r"""\mathlibok"""

    def digest(self, tokens):
        Command.digest(self, tokens)
        self.parentNode.userdata['leanok'] = True
        self.parentNode.userdata['mathlibok'] = True


class lean(Command):
    r"""\lean{decl list} """
    args = 'decls:list:nox'

    def digest(self, tokens):
        Command.digest(self, tokens)
        decls = [dec.strip() for dec in self.attributes['decls']]
        self.parentNode.setUserData('leandecls', decls)
        all_decls = self.ownerDocument.userdata.setdefault('lean_decls', [])
        all_decls.extend(decls)


class discussion(Command):
    r"""\discussion{issue_number} """
    args = 'issue:str'

    def digest(self, tokens):
        Command.digest(self, tokens)
        self.parentNode.setUserData(
            'issue', self.attributes['issue'].lstrip('#').strip())


CHECKMARK_TPL = Template("""
    {% if obj.userdata.leanok and ('proved_by' not in obj.userdata or obj.userdata.proved_by.userdata.leanok ) %}
    ✓
    {% endif %}
""")

LEAN_DECLS_TPL = Template("""
    {% if obj.userdata.leandecls %}
    <button class="modal lean">L∃∀N</button>
    {% call modal('Lean declarations') %}
        <ul class="uses">
          {% for lean, url in obj.userdata.lean_urls %}
          <li><a href="{{ url }}" class="lean_decl">{{ lean }}</a></li>
          {% endfor %}
        </ul>
    {% endcall %}
    {% endif %}
""")

GITHUB_ISSUE_TPL = Template("""
    {% if obj.userdata.issue %}
    <a class="github_link" href="{{ obj.ownerDocument.userdata.project_github }}/issues/{{ obj.userdata.issue }}">Discussion</a>
    {% endif %}
""")

LEAN_LINKS_TPL = Template("""
  {% if thm.userdata['lean_urls'] -%}
    {%- if thm.userdata['lean_urls']|length > 1 -%}
  <div class="tooltip">
      <span class="lean_link">Lean</span>
      <ul class="tooltip_list">
        {% for name, url in thm.userdata['lean_urls'] %}
           <li><a href="{{ url }}" class="lean_decl">{{ name }}</a></li>
        {% endfor %}
      </ul>
  </div>
    {%- else -%}
    <a class="lean_link lean_decl" href="{{ thm.userdata['lean_urls'][0][1] }}">Lean</a>
    {%- endif -%}
    {%- endif -%}
""")

GITHUB_LINK_TPL = Template("""
  {% if thm.userdata['issue'] -%}
  <a class="issue_link" href="{{ document.userdata['project_github'] }}/issues/{{ thm.userdata['issue'] }}">Discussion</a>
  {%- endif -%}
""")

SUBGRAPH_LINK_TPL = Template("""
  {% set node_id_safe = thm.id.replace(':', '_').replace('/', '_') -%}
  {% set subgraph_url = 'subgraph_' + node_id_safe + '.html' -%}
  <a class="subgraph_link" href="{{ subgraph_url }}">View Dependency Graph</a>
""")


def serialize_node(node):
    """
    序列化单个节点对象，提取所有相关信息。
    
    Args:
        node: 依赖图中的节点对象
        
    Returns:
        dict: 包含节点 ID、类型和所有 userdata 的字典
    """
    # 获取节点的基本信息
    node_data = {
        'id': node.id,
        'kind': item_kind(node),
    }
    
    # 获取节点的标题/标题（如果有）
    if hasattr(node, 'caption') and node.caption:
        node_data['caption'] = str(node.caption)
    else:
        # 如果没有 caption，使用 ID 的最后一部分作为标题
        node_data['title'] = node.id.split(':')[-1]
    
    # 序列化所有 userdata
    userdata = {}
    for key in node.userdata.keys():
        value = node.userdata.get(key)
        # 跳过无法序列化的对象（如函数、其他节点对象等）
        if isinstance(value, (str, int, float, bool, type(None))):
            userdata[key] = value
        elif isinstance(value, (list, tuple)):
            # 处理列表/元组，递归处理其中的元素
            serialized_list = []
            for item in value:
                if isinstance(item, (str, int, float, bool, type(None))):
                    serialized_list.append(item)
                elif isinstance(item, (list, tuple)):
                    # 如果是嵌套的列表/元组，转换为列表
                    serialized_list.append(list(item) if isinstance(item, tuple) else item)
                elif hasattr(item, 'id'):
                    # 如果是节点对象，只保存 ID
                    serialized_list.append(item.id)
                else:
                    # 尝试转换为字符串
                    try:
                        serialized_list.append(str(item))
                    except:
                        pass
            userdata[key] = serialized_list
        elif hasattr(value, 'id'):
            # 如果是节点对象（如 proved_by），只保存其 ID
            userdata[key] = value.id
        else:
            # 尝试转换为字符串
            try:
                userdata[key] = str(value)
            except:
                pass
    
    node_data['userdata'] = userdata
    return node_data


def serialize_graph(graph):
    """
    序列化依赖图对象，包括所有节点和边。
    
    Args:
        graph: DepGraph 实例
        
    Returns:
        dict: 包含节点列表、边列表和证明边列表的字典
    """
    # 序列化所有节点
    nodes = [serialize_node(node) for node in graph.nodes]
    
    # 序列化边（使用节点 ID）
    edges = [(s.id, t.id) for s, t in graph.edges]
    
    # 序列化证明边（使用节点 ID）
    proof_edges = [(s.id, t.id) for s, t in graph.proof_edges]
    
    return {
        'nodes': nodes,
        'edges': edges,
        'proof_edges': proof_edges,
        'node_count': len(nodes),
        'edge_count': len(edges),
        'proof_edge_count': len(proof_edges)
    }


def export_to_json(document, output_path: Path = None):
    """
    将 document.userdata 中的蓝图数据导出为 JSON 文件。
    
    包括：
    - 项目元数据（project_home, project_github, project_dochome）
    - 所有 Lean 声明列表
    - 依赖图数据（包括所有节点和边）
    - 颜色配置和图例
    
    Args:
        document: plasTeX 文档对象
        output_path: 输出 JSON 文件路径，如果为 None 则使用默认路径
        
    Returns:
        Path: 输出文件的路径
    """
    if output_path is None:
        # 默认输出到工作目录的父目录
        output_path = Path(document.userdata.get('working-dir', '.')).parent / 'blueprint_data.json'
    
    # 构建可序列化的数据结构
    data = {
        'project_metadata': {
            'project_home': document.userdata.get('project_home'),
            'project_github': document.userdata.get('project_github'),
            'project_dochome': document.userdata.get('project_dochome'),
        },
        'lean_decls': document.userdata.get('lean_decls', []),
    }
    
    # 序列化依赖图数据
    if 'dep_graph' in document.userdata:
        dep_graph_data = document.userdata['dep_graph']
        
        # 序列化颜色配置
        colors = {}
        if 'colors' in dep_graph_data:
            for key, value in dep_graph_data['colors'].items():
                if isinstance(value, (list, tuple)) and len(value) == 2:
                    colors[key] = {
                        'color': value[0],
                        'description': value[1]
                    }
                else:
                    colors[key] = value
        
        # 序列化图例
        legend = []
        if 'legend' in dep_graph_data:
            for item in dep_graph_data['legend']:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    legend.append({
                        'label': item[0],
                        'description': item[1]
                    })
                else:
                    legend.append(item)
        
        data['dep_graph'] = {
            'colors': colors,
            'legend': legend,
            'graphs': {}
        }
        
        # 序列化每个图
        if 'graphs' in dep_graph_data:
            for sec_name, graph in dep_graph_data['graphs'].items():
                data['dep_graph']['graphs'][sec_name] = serialize_graph(graph)
    
    # 写入 JSON 文件
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info(f'Exported blueprint data to {output_path}')
        return output_path
    except Exception as e:
        log.warning(f'Error exporting blueprint data to JSON: {e}')
        raise


def ProcessOptions(options, document):
    """This is called when the package is loaded."""

    # Extend DepGraph class with subgraph method using monkey patching
    def subgraph(self, node):
        """
        Create a subgraph containing the given node and all its ancestors (dependencies).
        Returns a new DepGraph instance, or None if node is not in the graph.
        """
        if node not in self.nodes:
            return None
        
        # Get all ancestor nodes (dependencies)
        ancestor_nodes = self.ancestors(node)
        subgraph_nodes = ancestor_nodes.union({node})
        
        # Create new DepGraph instance
        sub = DepGraph()
        sub.document = self.document
        sub.nodes = subgraph_nodes
        
        # Only include edges within the subgraph
        for s, t in self.edges:
            if s in subgraph_nodes and t in subgraph_nodes:
                sub.edges.add((s, t))
        for s, t in self.proof_edges:
            if s in subgraph_nodes and t in subgraph_nodes:
                sub.proof_edges.add((s, t))
        
        return sub
    
    # Monkey patch: dynamically add method to DepGraph class
    DepGraph.subgraph = subgraph

    # We want to ensure the depgraph and showmore packages are loaded.
    # We first need to make sure the corresponding plugins are used.
    # This is a bit hacky but needed for backward compatibility with
    # project who used the blueprint package before the depgraph one was
    # split.
    plugins = document.config['general'].data['plugins'].value
    if 'plastexdepgraph' not in plugins:
        plugins.append('plastexdepgraph')
    # And now load the package.
    document.context.loadPythonPackage(document, 'depgraph', options)
    if 'showmore' in options:
        if 'plastexshowmore' not in plugins:
            plugins.append('plastexshowmore')
        # And now load the package.
        document.context.loadPythonPackage(document, 'showmore', {})

    templatedir = PackageTemplateDir(path=PKG_DIR/'renderer_templates')
    document.addPackageResource(templatedir)

    jobname = document.userdata['jobname']
    outdir = document.config['files']['directory']
    outdir = string.Template(outdir).substitute({'jobname': jobname})

    def make_lean_data() -> None:
        """
        Build url and formalization status for nodes in the dependency graphs.
        Also create the file lean_decls of all Lean names referred to in the blueprint.
        """

        project_dochome = document.userdata.get('project_dochome',
                                                'https://leanprover-community.github.io/mathlib4_docs')

        for graph in document.userdata['dep_graph']['graphs'].values():
            nodes = graph.nodes
            for node in nodes:
                leandecls = node.userdata.get('leandecls', [])
                lean_urls = []
                for leandecl in leandecls:
                    lean_urls.append(
                        (leandecl,
                         f'{project_dochome}/find/#doc/{leandecl}'))

                node.userdata['lean_urls'] = lean_urls

                used = node.userdata.get('uses', [])
                node.userdata['can_state'] = all(thm.userdata.get('leanok')
                                                 for thm in used) and not node.userdata.get('notready', False)
                proof = node.userdata.get('proved_by')
                if proof:
                    used.extend(proof.userdata.get('uses', []))
                    node.userdata['can_prove'] = all(thm.userdata.get('leanok')
                                                     for thm in used)
                    node.userdata['proved'] = proof.userdata.get(
                        'leanok', False)
                else:
                    node.userdata['can_prove'] = False
                    node.userdata['proved'] = False

            for node in nodes:
                node.userdata['fully_proved'] = all(n.userdata.get('proved', False) or item_kind(
                    n) == 'definition' for n in graph.ancestors(node).union({node}))

        lean_decls_path = Path(document.userdata['working-dir']).parent/"lean_decls"
        lean_decls_path.write_text("\n".join(document.userdata.get("lean_decls", [])))

    document.addPostParseCallbacks(150, make_lean_data)

    document.addPackageResource([PackageCss(path=STATIC_DIR/'blueprint.css')])

    colors = document.userdata['dep_graph']['colors'] = {
        'mathlib': ('darkgreen', 'Dark green'),
        'stated': ('green', 'Green'),
        'can_state': ('blue', 'Blue'),
        'not_ready': ('#FFAA33', 'Orange'),
        'proved': ('#9CEC8B', 'Green'),
        'can_prove': ('#A3D6FF', 'Blue'),
        'defined': ('#B0ECA3', 'Light green'),
        'fully_proved': ('#1CAC78', 'Dark green')
    }

    def colorizer(node) -> str:
        data = node.userdata

        color = ''
        if data.get('mathlibok'):
            color = colors['mathlib'][0]
        elif data.get('leanok'):
            color = colors['stated'][0]
        elif data.get('can_state'):
            color = colors['can_state'][0]
        elif data.get('notready'):
            color = colors['not_ready'][0]
        return color

    def fillcolorizer(node) -> str:
        data = node.userdata
        stated = data.get('leanok')
        can_state = data.get('can_state')
        can_prove = data.get('can_prove')
        proved = data.get('proved')
        fully_proved = data.get('fully_proved')

        fillcolor = ''
        if proved:
            fillcolor = colors['proved'][0]
        elif can_prove and (can_state or stated):
            fillcolor = colors['can_prove'][0]
        if item_kind(node) == 'definition':
            if stated:
                fillcolor = colors['defined'][0]
            elif can_state:
                fillcolor = colors['can_prove'][0]
        elif fully_proved:
            fillcolor = colors['fully_proved'][0]
        return fillcolor

    document.userdata['dep_graph']['colorizer'] = colorizer
    document.userdata['dep_graph']['fillcolorizer'] = fillcolorizer

    def make_legend() -> None:
        """
        Extend the dependency graph legend defined by the depgraph plugin
        by adding information specific to Lean blueprints. This is registered
        as a post-parse callback to allow users to redefine colors and their 
        descriptions.
        """
        document.userdata['dep_graph']['legend'].extend([
            (f"{document.userdata['dep_graph']['colors']['can_state'][1]} border",
             "the <em>statement</em> of this result is ready to be formalized; all prerequisites are done"),
            (f"{document.userdata['dep_graph']['colors']['not_ready'][1]} border",
                "the <em>statement</em> of this result is not ready to be formalized; the blueprint needs more work"),
            (f"{document.userdata['dep_graph']['colors']['can_state'][1]} background",
                "the <em>proof</em> of this result is ready to be formalized; all prerequisites are done"),
            (f"{document.userdata['dep_graph']['colors']['proved'][1]} border",
                "the <em>statement</em> of this result is formalized"),
            (f"{document.userdata['dep_graph']['colors']['proved'][1]} background",
                "the <em>proof</em> of this result is formalized"),
            (f"{document.userdata['dep_graph']['colors']['fully_proved'][1]} background", 
                "the <em>proof</em> of this result and all its ancestors are formalized"),
            (f"{document.userdata['dep_graph']['colors']['mathlib'][1]} border",
                "this is in Mathlib"),
        ])

    document.addPostParseCallbacks(150, make_legend)

    document.userdata.setdefault(
        'thm_header_extras_tpl', []).extend([CHECKMARK_TPL])
    document.userdata.setdefault('thm_header_hidden_extras_tpl', []).extend([LEAN_DECLS_TPL,
                                                                             GITHUB_ISSUE_TPL])
    document.userdata['dep_graph'].setdefault('extra_modal_links_tpl', []).extend([
        LEAN_LINKS_TPL, GITHUB_LINK_TPL, SUBGRAPH_LINK_TPL])

    # Generate subgraph HTML files for each node
    def make_subgraph_html(document):
        """
        Generate subgraph HTML files for each node in the dependency graphs.
        Each subgraph shows the node and all its dependencies.
        """
        try:
            # Check if dependency graphs exist
            if 'dep_graph' not in document.userdata:
                return []
            
            graphs = document.userdata['dep_graph'].get('graphs', {})
            if not graphs:
                return []
            
            # Find template using the same method as depgraph package
            from plastexdepgraph.Packages.depgraph import PKG_DIR as DEPGRAPH_PKG_DIR
            default_tpl_path = DEPGRAPH_PKG_DIR.parent / 'templates' / 'dep_graph.html'
            
            # If not found, try alternative locations
            if not default_tpl_path.exists():
                # Try to find in installed package location
                try:
                    import plastexdepgraph
                    depgraph_pkg_dir = Path(plastexdepgraph.__file__).parent
                    default_tpl_path = depgraph_pkg_dir.parent / 'templates' / 'dep_graph.html'
                except (ImportError, AttributeError):
                    pass
            
            if not default_tpl_path.exists():
                return []
            
            graph_tpl = Template(default_tpl_path.read_text())
            
            # Get options from document userdata (set by depgraph package)
            reduce_graph = not document.userdata.get('dep_graph', {}).get('nonreducedgraph', False)
            
            files = []
            total_nodes = 0
            for sec, graph in graphs.items():
                total_nodes += len(graph.nodes)
                
                for node in graph.nodes:
                    sub = graph.subgraph(node)  # Use the monkey-patched method
                    if sub and len(sub.nodes) > 1:  # Only generate if there are dependencies
                        # Create a safe filename from node ID
                        node_id_safe = node.id.replace(':', '_').replace('/', '_')
                        graph_target = f'subgraph_{node_id_safe}.html'
                        files.append(graph_target)
                        
                        # Generate DOT representation
                        dot = sub.to_dot(document.userdata['dep_graph'].get('shapes', {'definition': 'box'}))
                        if reduce_graph:
                            dot = dot.tred()
                        
                        # Generate subgraph title
                        node_title = node.id.split(':')[-1]
                        if hasattr(node, 'caption') and node.caption:
                            node_title = str(node.caption)
                        subgraph_title = f'Dependencies of {node_title}'
                        
                        # Render HTML
                        graph_tpl.stream(
                            graph=sub,
                            dot=dot.to_string(),
                            context=document.context,
                            title=subgraph_title,
                            legend=document.userdata['dep_graph']['legend'],
                            extra_modal_links=document.userdata['dep_graph'].get('extra_modal_links_tpl', []),
                            document=document,
                            config=document.config
                        ).dump(graph_target)
            
            if files:
                log.info(f'Generated {len(files)} subgraph HTML files from {len(graphs)} graph(s) with {total_nodes} total nodes')
            return files
        
        except Exception as e:
            log.warning(f'Error generating subgraphs: {e}')
            return []
    
    # Register callback to generate subgraphs after main graphs are created
    # Only if subgraph option is enabled (via environment variable)
    # Use a higher priority (lower number) than the main graph generation (110)
    # but after make_lean_data (150) to ensure all node data is ready
    import os
    if os.environ.get('LEANBLUEPRINT_SUBGRAPH') == '1':
        cb = PackagePreCleanupCB(data=make_subgraph_html)
        document.addPackageResource(cb)
    
    # Export blueprint data to JSON file
    def export_json_callback() -> None:
        """
        导出蓝图数据为 JSON 的回调函数。
        在所有数据处理完成后执行，确保所有数据都已准备好。
        """
        try:
            export_to_json(document)
        except Exception as e:
            log.warning(f'Failed to export blueprint data to JSON: {e}')
    
    # 在 make_lean_data 之后执行（优先级 200，确保所有数据都已处理）
    document.addPostParseCallbacks(200, export_json_callback)