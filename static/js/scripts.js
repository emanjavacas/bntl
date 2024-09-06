
$(document).ready(function() {
    // Disable browser validation
    (function () {
        'use strict'
        // Fetch all the forms we want to apply custom Bootstrap validation styles to
        var forms = document.querySelectorAll('.needs-validation')
        // Loop over them and prevent submission
        Array.prototype.slice.call(forms)
            .forEach(function (form) {
                form.addEventListener('submit', function (event) {
                if (!form.checkValidity()) {
                    event.preventDefault()
                    event.stopPropagation()
                }    
                form.classList.add('was-validated')
            }, false)
        })
    })()

    // make sure regex checkbox is checked if the case checkbox is checked
    $.each(["author", "title", "keywords"], function(key, val) {
        $(`#${val}_case_id`).change(function(){
            if ($(this).is(":checked")) {
                $(`#${val}_regex_id`).prop("checked", true);
            }
        })
    })

    // advanced search on search.html
    $('#searchForm').on('submit', function (event) {
        $("#loadingModal").modal("show");
        event.preventDefault();
        const formArray = $(this).serializeArray();
        const formData = {};
        $.each(formArray, function(index, field){
            if (field.value !== "") {
                if (field.name.includes("regex") || field.name.includes("case")) {
                    console.log(field)
                    formData[field.name] = true;
                } else {
                    formData[field.name] = field.value;
                }
            }
        })
        $.ajax({
            type: 'POST',
            url: '/registerQuery',
            data: JSON.stringify(formData),
            contentType: 'application/json',
            success: function(response) {
                window.location.href = '/paginate?query_id=' + response.query_id;
            },
            error: function(response) {
                $("#errorModal").modal("show");
            }
        });
    });

    // full text search on index.html
    $('#fullText').on('submit', function (event) {
        $("#loadingModal").modal("show");
        event.preventDefault();
        const formData = {"full_text": $(this).serializeArray()[0].value}
        $.ajax({
            type: 'POST',
            url: '/registerQuery',
            data: JSON.stringify(formData),
            contentType: 'application/json',
            success: function(response) {
                window.location.href = '/paginate?query_id=' + response.query_id;
            },
            error: function(response) {
                console.log("Error", response);
            }
        });
    });
    
    // search within results on results.html
    $('#withinForm').on('submit', function (event) {
        $('#loadingModal').modal("show");
        event.preventDefault();
        const queryStr = $(this).serializeArray()[0].value;
        const queryId = new URLSearchParams(window.location.search).get("query_id");
        fetch("/paginateWithin?query_id=" + queryId + "&query_str=" + queryStr).then(
            function(resp){
                if (resp.ok) {window.location.href = resp.url}
            }
        ).catch(
            function(resp){console.log(resp)}
        )
    });

    // keyword autocomplete
    const keywordsCache = {};
    $('#keywords-input').autocomplete({
        minLength: 3,
        select: function(event, ui) {
            console.log("Selected, " + ui.item.value);
        },
        source: function(request, response) {
            // cache
            const term = request.term;
            if (term in keywordsCache) {
                response(keywordsCache[term]); 
                return; 
            }

            // fetch from DB
            $.ajax({
                url: "/query-keywords",
                type: "GET",
                data: {query: term},
                success: function(data) {
                    keywordsCache[term] = data;
                    response(data);
                },
                error: function(data) {
                    console.log(data);
                    response(data);
                }
            });
        }
    });

});