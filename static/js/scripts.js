
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

        // // nullify fields if they're empty
        // $(this).find('input[name]')
        //     .filter(function () {
        //         return !this.value;
        //     })
        //     .prop('name', '');
        // $(this).find('select')
        // // nullify select
        // if ($('#type_of_reference_select').val() === '') {
        //     $('#type_of_reference_select').prop('disabled', true);
        // }

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
        console.log(formData);
        
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