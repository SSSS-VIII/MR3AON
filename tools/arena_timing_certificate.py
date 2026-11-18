"""Strict coverage check for independent 80 ms original-engine input tests."""


def valid(certificate,start_frame,end_frame,operation_count):
    if not(certificate.get('passed')and certificate.get('window_ms')==80
           and certificate.get('independent')is True and certificate.get('scope')=='whole_board_suffix'
           and certificate.get('covers_start_frame')==start_frame
           and certificate.get('covers_end_frame')==end_frame
           and certificate.get('operations')==operation_count
           and certificate.get('offsets_ms')==[-40,-20,0,20,40]):return False
    checks=certificate.get('checks',[])
    expected={(event,offset)for event in range(operation_count)for offset in(-40,-20,0,20,40)}
    return (len(checks)==len(expected)and all(c.get('passed')is True for c in checks)
            and {(c.get('event'),c.get('shift_ms'))for c in checks}==expected)
