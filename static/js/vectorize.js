
const { div, li, ul, span, button, h5, form, input, p, small, br } = van.tags;

$(document).ready(function(){

    // state
    const tasklist = van.state(new TaskList([]));

    function addTaskToList(taskId, status, progress=0) {
        tasklist.val = tasklist.val.add(taskId, status, progress);
    }

    function updateTaskStatus(taskId, status, progress) {
        tasklist.val = tasklist.val.updateStatus(taskId, status, progress);
    }

    function onSubmit(e) {
        e.preventDefault();
        $.ajax({
            url: "/vectorize",
            type: "POST",
            success: function(response) {
                addTaskToList(response.taskId, STATUS.VECTORIZING);
                checkStatus(response.taskId);
            },
            error: function (xhr, status, error) {
                console.error(`Couldn't start task: ${status} - ${error}`);
                // TODO: trigger error badge
                const message = `Error: ${xhr.status} - ${xhr.responseJSON.detail || error}`
                showToast(message, "danger");
            }
        })
    }

    function isStatusDone(status) {
        return (
            status === STATUS.DONE ||
            status === STATUS.UNKNOWNERROR ||
            status === STATUS.VECTORIZINGERROR ||
            status === STATUS.VECTORINDEXINGERROR
        )
    }

    function checkStatus(taskId) {
        var interval = setInterval(function() {
            $.ajax({
                url: `/checkVectorizationStatus/${taskId}`,
                type: 'GET',
                success: function(response) {
                    updateTaskStatus(taskId, response.current_status.status, response.current_status.progress);
                    if (isStatusDone(response.current_status.status)) {
                        clearInterval(interval);
                    }
                },
                error: function() {
                    // set error
                    updateTaskStatus(taskId, STATUS.UNKNOWNERROR);
                    clearInterval(interval);
                }
            });
        }, 2000);
    }   

    // layout
    function Card() {
        function createListItem(task) {
            var statusClass = 'bg-warning text-dark';
            switch (task.status.val) {
                case STATUS.VECTORIZING:
                    statusClass = 'bg-warning text-dark'; break;
                case STATUS.DONE:
                    statusClass = 'bg-success'; break;
                case STATUS.UNKNOWNERROR: case STATUS.VECTORIZINGERROR: case STATUS.VECTORINDEXINGERROR:
                    statusClass = 'bg-danger'
            }

            const listItem = li({ class: 'list-group-item' },
                div({ class: "container-fluid py-1 px-0"},
                    div({ class: "row" }, 
                        div({ class: "col-8" },
                            button({ class: "btn btn-light position-relative disabled" },
                                trimString(task.taskId),
                                span({ style: "font-size:10px;", 
                                        class: `position-absolute top-100 start-100 translate-middle badge rounded-pill ${statusClass}` }, 
                                    task.status.val))),
                        div({ class: "col-4" },
                            // download button enabled
                            button({ id: `btn-${task.taskId}`, 
                                class: "btn btn-sm btn-primary float-end",
                                onclick: () => downloadLog(task.taskId) }, "Log") 
                            )
                        )
                )
            )
            return listItem
        }

        return div({ class: "card" }, 
            div({ class: "card-header" }, "Vectorization service"),
            div({ class: "card-body" },
                p({ class: "card-text" }, "Trigger a full vectorization of the database"),
                div(ul({ class: "list-group list-group-flush scroll", id: "taskList" },
                    () => div(tasklist.val.tasks.map(createListItem)))),
                div({class: "row pt-2 m-1"},
                    button({ class: "btn btn-outline-danger", type: "submit", onclick: onSubmit}, "Vectorize"))
            )
        )
    }

    van.add($("#vectorizationEntryPoint"), Card());
    // recall upload history
    $.ajax({
        url: "getVectorizationHistory",
        type: 'GET',
        success: function(response) {
            $.each(response, function(index, item) {
                if (!isStatusDone(item.current_status.status)){ checkStatus(item.task_id); }
                addTaskToList(item.task_id, item.current_status.status, item.current_status.progress | 0);
            })
        },
        error: function() { }
    });

});


class TaskList {
    constructor (tasks) { this.tasks = tasks }
    add (taskId, status, progress=0) {
        this.tasks.unshift({ 
            taskId: taskId,
            status: van.state(status), 
            progress: van.state(progress) });
        return new TaskList(this.tasks);
    }
    updateStatus(taskId, status, progress) {
        const task = this.tasks.find(f => f.taskId === taskId);
        if (task) {
            // never downgrade from DONE
            if (task.status.val !== STATUS.DONE) {
                task.status = van.state(status);
                task.progress = van.state(progress);
            }
        }
        return new TaskList(this.tasks);
    }
}

function downloadLog(taskId) {
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = `/getVectorizationLog?task_id=${taskId}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

function trimString(input) {
    if (input.length > 10) {
        return input.slice(0, 10) + '...';
    }
    return input;
}
