import { useCallback, useRef } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlowProvider,
  useReactFlow,
  type Node,
} from "reactflow";
import "reactflow/dist/style.css";
import { NodePanel } from "@/components/workflow/NodePanel";
import { PropertiesPanel } from "@/components/workflow/PropertiesPanel";
import { Toolbar } from "@/components/workflow/Toolbar";
import { workflowNodeTypes } from "@/components/workflow/nodeTypes";
import { useWorkflowStore } from "@/stores/workflowStore";
import type { WorkflowNodeData, WorkflowNodeType } from "@/types/workflow";

function WorkflowCanvas() {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const { project } = useReactFlow();

  const nodes = useWorkflowStore((s) => s.nodes);
  const edges = useWorkflowStore((s) => s.edges);
  const onNodesChange = useWorkflowStore((s) => s.onNodesChange);
  const onEdgesChange = useWorkflowStore((s) => s.onEdgesChange);
  const onConnect = useWorkflowStore((s) => s.onConnect);
  const addNode = useWorkflowStore((s) => s.addNode);
  const setSelectedNodeId = useWorkflowStore((s) => s.setSelectedNodeId);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData("application/reactflow");
      if (!raw || !reactFlowWrapper.current) return;
      let payload: { type: WorkflowNodeType; label: string };
      try {
        payload = JSON.parse(raw) as { type: WorkflowNodeType; label: string };
      } catch {
        return;
      }
      const bounds = reactFlowWrapper.current.getBoundingClientRect();
      const position = project({
        x: e.clientX - bounds.left,
        y: e.clientY - bounds.top,
      });
      const id = `${payload.type}-${crypto.randomUUID().slice(0, 8)}`;
      const newNode: Node<WorkflowNodeData, WorkflowNodeType> = {
        id,
        type: payload.type,
        position,
        data: { title: payload.label } as WorkflowNodeData,
      };
      addNode(newNode);
    },
    [addNode, project]
  );

  return (
    <div className="h-screen w-full flex">
      <NodePanel />
      <div
        className="relative min-h-0 min-w-0 flex-1"
        ref={reactFlowWrapper}
        onDragOver={onDragOver}
        onDrop={onDrop}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={workflowNodeTypes}
          onSelectionChange={({ nodes: sel }) => {
            setSelectedNodeId(sel[0]?.id ?? null);
          }}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Controls className="!m-2 !rounded-lg !border !border-border !bg-card/95 !shadow-lg" />
          <MiniMap
            className="!m-2 !rounded-lg !border !border-border !bg-card/90"
            zoomable
            pannable
          />
          <Background gap={20} size={1} color="hsl(217 33% 22%)" />
          <Panel position="top-center">
            <Toolbar />
          </Panel>
        </ReactFlow>
      </div>
      <PropertiesPanel />
    </div>
  );
}

export function WorkflowEditor() {
  return (
    <ReactFlowProvider>
      <WorkflowCanvas />
    </ReactFlowProvider>
  );
}
