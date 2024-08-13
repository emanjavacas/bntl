
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

    $('#searchForm').on('submit', function (event) {
        event.preventDefault();
        const formArray = $(this).serializeArray();
        const formData = {};
        $.each(formArray, function(index, field){
            if (field.value !== "") {
                if (field.name.includes("regex")) {
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
            }
        });
    });

    $('#fullText').on('submit', function (event) {
        event.preventDefault();
        const formData = {}
        formData["full_text"] = $(this).serializeArray()[0].value;
        $.ajax({
            type: 'POST',
            url: '/registerQuery',
            data: JSON.stringify(formData),
            contentType: 'application/json',
            success: function(response) {
                window.location.href = '/paginate?query_id=' + response.query_id;
            }
        });
    });
});