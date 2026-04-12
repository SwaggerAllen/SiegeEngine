import { Link, useNavigate } from 'react-router-dom';
import { useProjects } from '../hooks/queries/useProjectQueries';
import { useDeleteProject, useCloneProject } from '../hooks/mutations/useProjectMutations';
import { useAuthStore } from '../store/authStore';

export function ProjectListPage() {
  const { data: projects, isLoading } = useProjects();
  const deleteProjectMutation = useDeleteProject();
  const cloneProjectMutation = useCloneProject();
  const { logout, user } = useAuthStore();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <header className="border-b border-gray-700 px-6 py-4 flex items-center justify-between">
        <h1 className="text-xl font-bold">SiegeEngine</h1>
        <div className="flex items-center gap-4">
          <span className="text-gray-400 text-sm">{user?.username}</span>
          <button
            onClick={logout}
            className="text-sm text-gray-400 hover:text-white"
          >
            Logout
          </button>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-semibold">Projects</h2>
          <Link
            to="/projects/new"
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium"
          >
            New Project
          </Link>
        </div>

        {isLoading ? (
          <p className="text-gray-400">Loading...</p>
        ) : !projects || projects.length === 0 ? (
          <div className="text-center py-16">
            <p className="text-gray-400 mb-4">No projects yet</p>
            <Link
              to="/projects/new"
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium"
            >
              Create your first project
            </Link>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {projects.map((project) => (
              <div
                key={project.id}
                className="bg-gray-800 rounded-lg p-5 border border-gray-700 hover:border-gray-500 cursor-pointer transition"
                onClick={() => navigate(`/projects/${project.id}`)}
              >
                <h3 className="font-semibold text-lg mb-1">{project.name}</h3>
                <p className="text-gray-400 text-sm mb-3 line-clamp-2">
                  {project.description || 'No description'}
                </p>
                <div className="flex items-center justify-end text-xs text-gray-500">
                  <div className="flex gap-3">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        cloneProjectMutation.mutate({ id: project.id });
                      }}
                      disabled={cloneProjectMutation.isPending}
                      className="text-blue-400 hover:text-blue-300 disabled:opacity-50"
                    >
                      {cloneProjectMutation.isPending ? 'Cloning...' : 'Clone'}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm('Delete this project?')) deleteProjectMutation.mutate(project.id);
                      }}
                      className="text-red-400 hover:text-red-300"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
