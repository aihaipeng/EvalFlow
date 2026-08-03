let implementationPromise = null;
let activeImplementation = null;
let mountRequestId = 0;

function loadImplementation() {
    if (!implementationPromise) {
        implementationPromise = import('./workflow-canvas-implementation.jsx')
            .catch((error) => {
                implementationPromise = null;
                throw error;
            });
    }
    return implementationPromise;
}

async function mount(options = {}) {
    const requestId = ++mountRequestId;
    try {
        const implementation = await loadImplementation();
        if (requestId !== mountRequestId) return;
        activeImplementation = implementation;
        implementation.mount(options);
    } catch (error) {
        if (requestId !== mountRequestId) return;
        const detail = error instanceof Error ? error.message : String(error || '未知错误');
        if (typeof window.showToast === 'function') {
            window.showToast(`工作流画布加载失败：${detail}`, 'error');
        }
    }
}

function unmount() {
    mountRequestId += 1;
    activeImplementation?.unmount();
}

window.AgentBenchWorkflowCanvas = {mount, unmount};
