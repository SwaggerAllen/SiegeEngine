import { ArtifactTabLayout } from './ArtifactTabLayout';

export function DocumentsTab() {
  return (
    <ArtifactTabLayout
      variant="documents"
      defaultPaneOpen={false}
      closePaneOnDeselect
      defaultHandle={<span className="text-gray-500 text-xs flex-1">Select a node to review</span>}
      defaultContent={<div className="p-4 text-gray-500 text-sm">Select a node to see review options.</div>}
    />
  );
}
